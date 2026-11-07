"""#364: district-bound ranked preview, operational failures and source evidence."""

import html
import math
import sqlite3
from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.facts import FactStore
from app.main import app
from app.page_state import PageState
from etl.boundaries import all_districts

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_missing_store_is_operational_error(
    chamber: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "absent.db"))
    response = TestClient(app).get(f"/brief/{chamber}/22?preview=1")
    assert response.status_code == 200  # Flagged errors are contained by the brief.
    assert "the matches section could not be shown" in response.text
    assert "Matches fact store is missing" in caplog.text
    assert 'data-match="' not in response.text


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_missing_records_preserve_limits(
    chamber: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "empty.db"
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    response = TestClient(app).get(f"/brief/{chamber}/22?preview=1")
    assert response.status_code == 200
    article = response.text.split('data-match="disability:hawaii-able"', 1)[1].split("</article>")[
        0
    ]
    for text in (
        "People with a disability",
        "Relevant need only",
        "Program-expert review: pending",
        "Disability onset",
        "certification",
        "enrollment",
        "S1810_C02_001E",
        "Civilian noninstitutionalized population",
        "Not available",
        "not available",
        "https://www.ssa.gov/ssi/spotlights/spot-able.html",
        "https://www.auw211.org/",
        "agency decides eligibility",
        "insufficient",
        "No comparable prominence evidence",
    ):
        assert text in article
    assert "Comparable nonparticipation —" not in response.text


def test_preview_isolation() -> None:
    client = TestClient(app)
    assert 'data-match="' not in client.get("/brief/house/22").text
    assert 'data-match="' in client.get("/brief/house/22?preview=1").text


def test_all_districts_repeat_and_reconstruct_fact_calculations(
    matching_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import templates
    from app.tools.matches import DistrictMatches
    from etl.programs import Program

    section = import_module("app.sections.36_matches")
    # Validate immutable reference data once; every render still reads its own fact rows.
    tool_module = import_module("app.tools.matches")
    registry = tool_module.load_populations()
    mappings = tool_module.load_mappings()
    catalog = tool_module.load_catalog(tool_module.CATALOG)
    monkeypatch.setattr(tool_module, "load_populations", lambda: registry)
    monkeypatch.setattr(tool_module, "load_mappings", lambda: mappings)

    def cached_catalog(path: Path) -> list[Program]:
        return catalog

    monkeypatch.setattr(tool_module, "load_catalog", cached_catalog)
    monkeypatch.setattr(section, "load_populations", lambda: registry)
    monkeypatch.setattr(section, "load_mappings", lambda: mappings)
    template = templates.get_template("sections/36-matches.html")
    for district in all_districts("house") + all_districts("senate"):
        matches = DistrictMatches(district).get_matches()
        assert matches == DistrictMatches(district).get_matches()
        assert matches
        order = [(-m.result.score, m.program.id, m.population.id) for m in matches]
        assert order == sorted(order)
        state = PageState(district=district, preview=True)
        a = template.render(section=section.context(state), state=state)
        b = template.render(section=section.context(state), state=state)
        assert a == b
        for match in matches:
            assert match.result.claim == "relevant_need"
            assert match.result.uptake is None
            count = match.count
            count_facts = FactStore.default().get(
                ((c, district.fact_key) for c in count.numerator), "2020–2024"
            )
            count_value = sum(f.value or 0 for f in count_facts.values())
            count_moe = math.sqrt(sum((f.moe or 0) ** 2 for f in count_facts.values()))
            assert count.value == count_value
            assert count.moe == pytest.approx(count_moe)
            article = (
                html.unescape(a)
                .split(f'data-match="{match.population.id}:{match.program.id}"', 1)[1]
                .split("</article>", 1)[0]
            )
            assert f"{count_value:,.0f} {match.population.unit}" in article
            assert f"±{count_moe:,.0f}" in article
            for figure in match.result.figures:
                keys = [(c, figure.geography) for c in figure.numerator + figure.denominator]
                facts = FactStore.default().get(keys, "2020–2024")
                if figure.value is None:
                    assert figure.missing or all(f.value in (None, 0) for f in facts.values())
                    continue
                x = sum(facts[c, figure.geography].value or 0 for c in figure.numerator)
                y = sum(facts[c, figure.geography].value or 0 for c in figure.denominator)
                assert figure.value == pytest.approx(100 * x / y)
                mx2 = sum((facts[c, figure.geography].moe or 0) ** 2 for c in figure.numerator)
                my2 = sum((facts[c, figure.geography].moe or 0) ** 2 for c in figure.denominator)
                rad = mx2 - (x / y) ** 2 * my2
                expected = math.sqrt(rad if rad >= 0 else mx2 + (x / y) ** 2 * my2) / y * 100
                assert figure.moe == pytest.approx(expected)
                assert str(figure.value) in match.result.reason
                assert match.result.reason in html.unescape(a)


def test_invalid_district_cannot_scope_tool() -> None:
    from app.tools.matches import DistrictMatches

    with pytest.raises(ValueError, match="district"):
        DistrictMatches({"chamber": "house", "district": "22?other=1"})


@pytest.fixture
def matching_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic published-cell shapes, deliberately different district/state shares."""
    from decimal import Decimal

    from app.analysis.reliability import classify
    from app.models import Fact

    path = tmp_path / "matching.db"
    districts = all_districts("house") + all_districts("senate")
    geographies = [(d.fact_key, int(d.district)) for d in districts] + [("state:15", 0)]
    cells = ("B22003_006E", "B22003_003E", "S1810_C02_001E", "S1810_C01_001E")
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        for geo, number in geographies:
            values = (20 + number, 80, 10 + number, 100)
            for cell, value in zip(cells, values, strict=True):
                cv, flag = classify(Decimal(value), Decimal(2))
                fact = Fact(
                    variable=cell,
                    geography=geo,
                    vintage="2020–2024",
                    value=value,
                    moe=2,
                    cv=float(cv) if cv is not None else None,
                    reliability=flag,
                    source="Synthetic Census fixture",
                    table_id=cell.split("_")[0],
                    method="published estimate and 90% margin of error",
                    endpoint="https://example.org/synthetic",
                    label="Synthetic cell",
                )
                raw = fact.model_dump()
                db.execute(
                    f"INSERT INTO facts ({', '.join(raw)}) VALUES ({', '.join('?' for _ in raw)})",
                    tuple(raw.values()),
                )
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return path


def test_unsupported_comparison_and_weak_distinction(
    matching_store: Path,
) -> None:
    from app.tools.matches import DistrictMatches
    from etl.boundaries import DistrictId

    tool = DistrictMatches(DistrictId(chamber="house", district=22))
    assert any(m.result.band == "strong" for m in tool.get_matches())
    with sqlite3.connect(matching_store) as db:
        db.execute("DELETE FROM facts WHERE geography = 'state:15'")
    for match in tool.get_matches():
        assert "No comparable prominence evidence" in match.result.reason
        assert "Higher comparable" not in match.result.reason
        assert match.result.claim == "relevant_need"
        assert match.result.band == "possible"
    with sqlite3.connect(matching_store) as db:
        db.execute("UPDATE facts SET moe = 100, cv = 100 / 1.645 / value, reliability = 'caution'")
    assert all(m.result.band == "weak" for m in tool.get_matches())
    with sqlite3.connect(matching_store) as db:
        db.execute("DELETE FROM facts")
    assert all(m.result.band == "insufficient" for m in tool.get_matches())


def test_corrupt_store_does_not_become_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools.matches import DistrictMatches
    from etl.boundaries import DistrictId

    path = tmp_path / "corrupt.db"
    path.write_text("not sqlite")
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    with pytest.raises(sqlite3.DatabaseError, match="not a database"):
        DistrictMatches(DistrictId(chamber="senate", district=22)).get_matches()


def test_different_vintage_cannot_support_prominence(matching_store: Path) -> None:
    from app.tools.matches import DistrictMatches
    from etl.boundaries import DistrictId

    with sqlite3.connect(matching_store) as db:
        db.execute("UPDATE facts SET vintage = '2019–2023' WHERE geography = 'state:15'")
    for match in DistrictMatches(DistrictId(chamber="senate", district=22)).get_matches():
        assert "No comparable prominence evidence" in match.result.reason
        assert "Higher comparable" not in match.result.reason
        assert match.result.uptake is None
