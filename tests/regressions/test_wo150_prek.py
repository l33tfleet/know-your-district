"""#370: public pre-K coverage, complete match evidence and intact four-card print."""

import hashlib
import html
import json
import math
import sqlite3
from datetime import date
from importlib import import_module
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import Page

from app import features
from app.facts import FactStore
from app.main import templates
from app.page_state import PageState
from app.tools.matches import DistrictMatches
from etl.boundaries import DistrictId, all_districts
from etl.programs import Program, load_catalog
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page, page
from tests.regressions.test_wo143_integration import pdf_pages
from tests.regressions.test_wo149_matches import matching_store

__all__ = ["base_url", "browser", "matching_store", "page"]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def complete_store(matching_store: Path) -> Path:
    with sqlite3.connect(matching_store) as db:
        for (geo,) in db.execute("SELECT DISTINCT geography FROM facts").fetchall():
            for cell, value in zip(
                ("B01001_003E", "B01001_027E", "B01001_001E"),
                (20, 20, 100) if geo != "state:15" else (10, 10, 200),
                strict=True,
            ):
                db.execute(
                    "INSERT INTO facts SELECT ?, geography, vintage, ?, moe, "
                    "2 / 1.645 / ?, 'reliable', source, 'B01001', method, endpoint, label, NULL, NULL "
                    "FROM facts WHERE geography = ? LIMIT 1",
                    (cell, value, value, geo),
                )
        db.execute(
            "UPDATE facts SET value = 80, cv = 2 / 1.645 / 80 WHERE geography = 'state:15' "
            "AND variable IN ('B22003_006E', 'S1810_C02_001E')"
        )
    return matching_store


def test_legacy_serialization_and_one_extended_pilot() -> None:
    programs = load_catalog(ROOT / "data/programs.yaml")
    raw = yaml.safe_load((ROOT / "data/programs.yaml").read_text())
    assert len(programs) == 4
    for program_id, digest in {
        "snap": "04075a43b898878c8222428be3257c755dd7c835048ef45c57f0991231f64e91",
        "ga": "426cad0a88be43a88f31406f751f201ed8054d44801c15045d0eab5475541e7c",
    }.items():
        program = next(p for p in programs if p.id == program_id)
        original = next(p for p in raw if p["id"] == program_id)
        assert set(program.model_dump()) == set(original) | {"retired"}
        assert set(json.loads(program.model_dump_json())) == set(original) | {"retired"}
        assert not {"rules", "next_steps", "enrichment"} & program.model_dump().keys()
        serialized = json.dumps(program.model_dump(mode="json"), sort_keys=True)
        assert hashlib.sha256(serialized.encode()).hexdigest() == digest
    pilot = next(p for p in programs if p.id == "hawaii-able")
    # Keep the retained comparison regression focused on the enriched ABLE pilot.
    assert pilot.rules and pilot.next_steps and pilot.enrichment and programs[-1] == pilot
    assert Program.model_validate_json(pilot.model_dump_json()) == pilot
    for ref in pilot.enrichment.fact_references:
        assert FactStore.default().get([(ref.variable, ref.geography)], ref.vintage)


def test_pilot_urls_follow_catalog_link_policy() -> None:
    from etl.programs.links import LinkResponse, check_catalog

    programs = load_catalog(ROOT / "data/programs.yaml")
    report = check_catalog(
        programs, get=lambda _url, _timeout: LinkResponse(200), today=lambda: date(2026, 11, 8)
    )
    assert not report.failures


@pytest.mark.parametrize("path", ["/brief/house/22", "/brief/senate/5"])
@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
def test_pilot_preserves_one_page_with_wider_print_text(
    page: Page,
    base_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    variant: str,
) -> None:
    policy = tmp_path / "features.toml"
    policy.write_text('outreach = "on"\nprofiles = "on"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", policy)
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    open_page(page, base_url + path + variant, 1440)
    assert page.locator(".program").count() == 4 and page.locator(".profiles").is_visible()
    card_text = page.locator(".program-list").inner_text().split()
    page.emulate_media(media="print")
    assert not page.locator(".profiles").is_visible()
    assert all(card.is_visible() for card in page.locator(".program, .program a").all())
    assert page.locator(".program-list").inner_text().split() == card_text
    assert pdf_pages(page) == 1
    page.add_style_tag(content=".brief, .site-footer { letter-spacing: 0.04em; }")
    assert pdf_pages(page) == 1


def test_all_districts_repeat_and_reconstruct_fact_calculations(complete_store: Path) -> None:
    section = import_module("app.sections.36_matches")
    template = templates.get_template("sections/36-matches.html")
    for district in all_districts("house") + all_districts("senate"):
        matches = DistrictMatches(district).get_matches()
        assert matches and matches == DistrictMatches(district).get_matches()
        order = [(-m.result.score, m.program.id, m.population.id) for m in matches]
        assert order == sorted(order)
        state = PageState(district=district, preview=True)
        a = template.render(section=section.context(state), state=state)
        b = template.render(section=section.context(state), state=state)
        assert a == b
        for match in matches:
            assert match.result.claim == "relevant_need" and match.result.uptake is None
            count = match.count
            article = (
                html.unescape(a)
                .split(f'data-match="{match.population.id}:{match.program.id}"', 1)[1]
                .split("</article>", 1)[0]
            )
            assert f"{count.value:,.0f} {match.population.unit}" in article
            assert f"±{count.moe:,.0f}" in article
            for figure in (count, *match.result.figures):
                keys = [(c, figure.geography) for c in figure.numerator + figure.denominator]
                facts = FactStore.default().get(keys, "2020–2024")
                assert figure.geography in (district.fact_key, "state:15")
                if figure.value is None:
                    assert figure.missing or all(f.value in (None, 0) for f in facts.values())
                    continue
                x = sum(facts[c, figure.geography].value or 0 for c in figure.numerator)
                if figure.kind == "sum":
                    assert figure.value == x and figure.moe == pytest.approx(
                        math.sqrt(sum((f.moe or 0) ** 2 for f in facts.values()))
                    )
                    continue
                y = sum(facts[c, figure.geography].value or 0 for c in figure.denominator)
                assert figure.value == pytest.approx(100 * x / y)
                mx2 = sum((facts[c, figure.geography].moe or 0) ** 2 for c in figure.numerator)
                my2 = sum((facts[c, figure.geography].moe or 0) ** 2 for c in figure.denominator)
                rad = mx2 - (x / y) ** 2 * my2
                expected = math.sqrt(rad if rad >= 0 else mx2 + (x / y) ** 2 * my2) / y * 100
                assert figure.moe == pytest.approx(expected)
                assert str(figure.value) in match.result.reason
                assert match.result.reason in html.unescape(a)


def test_unsupported_comparison_and_weak_distinction(complete_store: Path) -> None:
    tool = DistrictMatches(DistrictId(chamber="house", district=22))
    assert any(m.result.band == "strong" for m in tool.get_matches())
    with sqlite3.connect(complete_store) as db:
        db.execute("DELETE FROM facts WHERE geography = 'state:15'")
    for match in tool.get_matches():
        assert "No comparable prominence evidence" in match.result.reason
        assert "Higher comparable" not in match.result.reason
        assert match.result.claim == "relevant_need" and match.result.band == "possible"
    with sqlite3.connect(complete_store) as db:
        db.execute("UPDATE facts SET moe = 100, cv = 100 / 1.645 / value, reliability = 'caution'")
    assert all(m.result.band == "weak" for m in tool.get_matches())
    with sqlite3.connect(complete_store) as db:
        db.execute("DELETE FROM facts")
    assert all(m.result.band == "insufficient" for m in tool.get_matches())


def test_prek_first_and_missing_evidence(complete_store: Path) -> None:
    tool = DistrictMatches(DistrictId(chamber="house", district=22))
    match = tool.get_matches()[0]
    assert match.program.id == "public-pre-k"
    assert match.result.band == "strong" and match.result.claim == "relevant_need"
    for text in [
        "Higher comparable population share",
        "Review: pending",
        *match.population.numerator,
        *match.population.denominator,
        "MOE",
        "reliable",
        "2020–2024",
    ]:
        assert text in match.result.reason
    assert match.program.eligibility_proxy.status == "unavailable"
    with sqlite3.connect(complete_store) as db:
        db.execute("DELETE FROM facts WHERE table_id = 'B01001'")
    for m in tool.get_matches():
        assert (m.result.band == "insufficient") == (m.program.id == "public-pre-k")
