"""#286 (journey step 1): the brief opens with the district's first outreach case.

The case is a validated record (`data/cases.yaml`, `app/cases.py`); its card sits after the
headline and before the figures, repeats section 40's district reading word for word, never
says "eligible", "qualify" or "not enrolled", and hides with the `outreach` flag.
Supersedes the load count in
test_wo136_answer.py::test_off_hides_form_and_route_and_skips_result_load: one load per
section that shows SNAP figures, still none from a disabled answer route.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import cases, features, snap
from app.main import app
from etl.boundaries import DISTRICT_COUNTS, DistrictId
from tests.regressions.test_wo97_brief_page import Node, parse

Configure = Callable[[str], TestClient]


@pytest.fixture
def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Configure:
    def write(text: str) -> TestClient:
        path = tmp_path / "features.toml"
        path.write_text(text)
        monkeypatch.setattr(features, "FEATURES_PATH", path)
        return TestClient(app)

    return write


def page(client: TestClient, path: str = "/brief/house/22") -> Node:
    response = client.get(path)
    assert response.status_code == 200
    return parse(response.text)


def flat(node: Node) -> str:
    return " ".join("".join(node.parts).split())


def order(tree: Node) -> list[str]:
    return [n.attrs.get("class", "") for n in tree.find_all() if n.tag in {"section", "header"}]


def test_every_district_opens_with_the_case_matching_section_40(configure: Configure) -> None:
    client = configure('outreach = "on"\n')
    for chamber, count in DISTRICT_COUNTS.items():
        for number in range(1, count + 1):
            tree = page(client, f"/brief/{chamber}/{number}")
            seen = order(tree)
            assert seen.index("brief-headline") < seen.index("case") < seen.index("figures")
            assert seen.index("case") < seen.index("outreach")
            card = tree.one("section", class_="case")
            evidence = tree.one("section", class_="outreach").one("tbody").find_all("tr")[0]
            reading = snap.load_result(
                DistrictId.model_validate({"chamber": chamber, "district": number})
            ).district
            line = f"{reading.value_text} {reading.units}; {reading.moe_text}; "
            line += reading.reliability_word
            assert line in flat(card.one(class_="case-reading"))
            assert line in flat(evidence)
            text = flat(card)
            assert "Households in poverty reporting no SNAP receipt · SNAP" in text
            assert "survey-reported receipt over the past 12 months" in text
            assert "outreach signal" in text
            lowered = text.lower()
            for banned in ("eligible", "qualify", "not enrolled"):
                assert banned not in lowered, (chamber, number, banned)
            hrefs = [a.attrs.get("href") for a in card.find_all("a")]
            assert "#outreach-heading" in hrefs
            assert "https://humanservices.hawaii.gov/bessd/snap/" in hrefs
            assert "https://humanservices.hawaii.gov/bessd/snap-outreach-providers/" in hrefs
            assert "https://auw211.org/" in hrefs


def test_card_says_what_is_known_the_gap_and_the_action(configure: Configure) -> None:
    card = page(configure('outreach = "on"\n')).one("section", class_="case")
    text = flat(card)
    assert "County and state figures, and the source" in text
    for words in ("B22003_006", "not in the survey", "Aloha United Way 211"):
        assert words in text
    # Rule 1: the card's number cites source, table, vintage, geography and method.
    fact = snap.load_result(DistrictId(chamber="house", district=22)).district.fact
    assert fact is not None
    source = flat(card.one(class_="case-source"))
    for cited in (fact.source, fact.table_id, fact.vintage, "District 22", "margin of error"):
        assert cited in source
    known = flat(card.one("dl", class_="case-evidence"))
    for problem in ("Geography", "Population", "Program"):
        assert problem in known
    assert card.find_all(class_="case-gap") and card.find_all(class_="case-action")
    # The reserved save slot renders only when a later step passes a control.
    assert not card.find_all(class_="case-save")


def test_missing_reading_says_so_and_keeps_the_next_step(
    configure: Configure, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snap, "SNAP_DB", tmp_path / "absent.db")
    card = page(configure('outreach = "on"\n')).one("section", class_="case")
    text = flat(card)
    assert "No published figure for this district yet" in text
    assert not card.find_all(class_="case-reading")
    hrefs = [a.attrs.get("href") for a in card.find_all("a")]
    assert "https://humanservices.hawaii.gov/bessd/snap/" in hrefs
    assert "https://auw211.org/" in hrefs


def test_missing_referrals_keep_official_page_and_211(
    configure: Configure, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snap, "REFERRALS_PATH", tmp_path / "absent.json")
    card = page(configure('outreach = "on"\n')).one("section", class_="case")
    hrefs = [a.attrs.get("href") for a in card.find_all("a")]
    assert "https://humanservices.hawaii.gov/bessd/snap/" in hrefs
    assert "https://auw211.org/" in hrefs
    assert "https://humanservices.hawaii.gov/bessd/snap-outreach-providers/" not in hrefs


def test_outreach_off_hides_the_card(configure: Configure, monkeypatch: pytest.MonkeyPatch) -> None:
    client = configure('outreach = "off"\n')

    def forbidden(district: DistrictId) -> snap.SnapResult:
        pytest.fail("disabled outreach must not load facts")

    monkeypatch.setattr(snap, "load_result", forbidden)
    tree = page(client)
    assert not tree.find_all("section", class_="case")


def test_answer_route_off_loads_only_for_the_cards(
    configure: Configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaces the load count of the superseded WO162 test, at least as strict."""
    client = configure('outreach = "on"\nsnap_question = "off"\n')
    calls: list[DistrictId] = []
    original = snap.load_result

    def counted(district: DistrictId) -> snap.SnapResult:
        calls.append(district)
        return original(district)

    monkeypatch.setattr(snap, "load_result", counted)
    for query in ("", "&preview=1"):
        tree = page(client, f"/brief/house/22?v=a{query}")
        assert not tree.find_all("section", class_="snap-question")
        response = client.get(f"/brief/house/22/snap-answer?question=no_snap_households{query}")
        assert response.status_code == 404
        assert "text/html" in response.headers["content-type"]
    assert client.get("/brief/house/22/snap-answer?question=other").status_code == 404
    # One load for the case card and one for the outreach evidence, per page; none from
    # the disabled answer route.
    assert len(calls) == 4


def record() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(cases.CASES_PATH.read_text(encoding="utf-8"))
    return loaded


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_shipped_record_is_the_snap_case() -> None:
    (case,) = cases.load_cases()
    assert case.population == "below_poverty_no_snap"
    assert case.failure.kind == "eligible_nonparticipation"
    assert set(case.known) == {"geography", "population"}
    assert set(case.unknown) == {"program"}
    assert "B22003_006" in case.known["population"]
    assert case.research.startswith("docs/research/benefit-program-access.md#")


def test_rejects_unknown_population(tmp_path: Path) -> None:
    data = record()
    data["cases"][0]["population"] = "no_such_population"
    with pytest.raises(ValueError, match="no_such_population"):
        cases.load_cases(write(tmp_path, data))


def test_rejects_unknown_gap_type(tmp_path: Path) -> None:
    data = record()
    data["cases"][0]["failure"]["kind"] = "low_awareness"
    with pytest.raises(ValidationError, match=r"failure\.kind"):
        cases.load_cases(write(tmp_path, data))


def test_rejects_unknown_action(tmp_path: Path) -> None:
    data = record()
    data["cases"][0]["action"]["kind"] = "door_knocking"
    with pytest.raises(ValidationError, match=r"action\.kind"):
        cases.load_cases(write(tmp_path, data))


def test_rejects_missing_unknown(tmp_path: Path) -> None:
    data = record()
    del data["cases"][0]["unknown"]
    with pytest.raises(ValidationError, match="unknown"):
        cases.load_cases(write(tmp_path, data))


def test_rejects_an_evidence_problem_left_out(tmp_path: Path) -> None:
    data = record()
    data["cases"][0]["unknown"] = {}
    with pytest.raises(ValidationError, match="program"):
        cases.load_cases(write(tmp_path, data))


def test_rejects_unknown_fields(tmp_path: Path) -> None:
    data = record()
    data["cases"][0]["eligibility"] = "everyone"
    with pytest.raises(ValidationError, match="extra"):
        cases.load_cases(write(tmp_path, data))


def test_card_says_the_survey_undercounts_receipt_beside_the_count(
    configure: Configure,
) -> None:
    """docs/data.md trap 3: the undercount caveat sits next to every benefit figure."""
    card = page(configure('outreach = "on"\n'), "/brief/senate/5").one("section", class_="case")
    why = flat(card.one(class_="case-why"))
    assert "Survey answers undercount benefit receipt" in why
    assert flat(card.one(class_="case-reading")) in why


def test_rejects_a_problem_both_known_and_unknown(tmp_path: Path) -> None:
    data = record()
    data["cases"][0]["unknown"]["geography"] = "contradicts the known entry"
    with pytest.raises(ValidationError, match="both known and unknown: geography"):
        cases.load_cases(write(tmp_path, data))


def test_rejects_a_duplicate_case_id(tmp_path: Path) -> None:
    data = record()
    data["cases"].append(data["cases"][0])
    with pytest.raises(ValueError, match="duplicate case id: snap_poverty_no_receipt"):
        cases.load_cases(write(tmp_path, data))
