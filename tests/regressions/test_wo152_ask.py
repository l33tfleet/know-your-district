"""#386: Ask selects references; all three surfaces render trusted match cards."""

from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from pydantic import ValidationError

from app.agent.answers import AnswerRenderer, parse_answer
from app.main import app
from etl.boundaries import DistrictId
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, browser, page
from tests.regressions.test_wo149_matches import matching_store
from tests.regressions.test_wo152_brief import dom

__all__ = ["browser", "matching_store", "page"]
DISTRICT = DistrictId(chamber="house", district=22)


def test_find_matches_returns_only_district_bound_references(matching_store: Path) -> None:
    from app.tools.matches import DistrictMatches, find_matches, resolve_matches

    references = find_matches(DISTRICT)
    matches = DistrictMatches(DISTRICT).get_matches()
    assert [(r.population_id, r.program_id) for r in references] == [
        (m.population.id, m.program.id) for m in matches
    ]
    assert all(r.district == DISTRICT for r in references)
    assert all(
        set(r.model_dump()) == {"district", "population_id", "program_id"} for r in references
    )
    selected = find_matches(DISTRICT, "below_poverty_no_snap")
    assert selected and all(r.population_id == "below_poverty_no_snap" for r in selected)
    assert resolve_matches(DISTRICT, selected) == tuple(
        m for m in matches if m.population.id == "below_poverty_no_snap"
    )


def test_unknown_population_is_rejected(matching_store: Path) -> None:
    from app.tools.matches import find_matches

    with pytest.raises(ValueError, match="Unknown population; valid:"):
        find_matches(DISTRICT, "invented")


@pytest.mark.parametrize("damage", ["district", "population", "program"])
def test_reference_cannot_escape_page_or_invent_match(matching_store: Path, damage: str) -> None:
    from app.tools.matches import MatchReference

    raw: dict[str, object] = {
        "district": DISTRICT.model_dump(),
        "population_id": "below_poverty_no_snap",
        "program_id": "snap",
    }
    if damage == "district":
        raw["district"] = {"chamber": "senate", "district": 22}
    elif damage == "population":
        raw["population_id"] = "invented"
    else:
        raw["program_id"] = "invented"
    answer = parse_answer(
        {
            "kind": "routed",
            "case_id": "snap_no_receipt",
            "confidence": 1,
            "match_references": [MatchReference.model_validate(raw).model_dump()],
        }
    )
    with pytest.raises(
        ValueError,
        match="outside page district" if damage == "district" else "unknown match reference",
    ):
        AnswerRenderer(DISTRICT, []).render(answer)


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", 999999),
        ("moe", 1),
        ("official_url", "https://evil.example/"),
        ("text", "999999 eligible"),
    ],
)
@pytest.mark.parametrize("location", ["answer", "reference"])
def test_model_cannot_author_card_numbers_links_or_prose(
    field: str, value: object, location: str
) -> None:
    reference: dict[str, object] = {
        "district": DISTRICT.model_dump(),
        "population_id": "below_poverty_no_snap",
        "program_id": "snap",
    }
    raw: dict[str, object] = {
        "kind": "routed",
        "case_id": "snap_no_receipt",
        "confidence": 1,
        "match_references": [reference],
    }
    (raw if location == "answer" else reference)[field] = value
    with pytest.raises(ValidationError, match="Extra inputs are not permitted") as error:
        parse_answer(raw)
    assert any(e["loc"][-1] == field for e in error.value.errors())


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_ask_card_has_identical_dom_on_three_surfaces(matching_store: Path, chamber: str) -> None:
    client = TestClient(app, client=("192.0.2.1", 1234))
    base = f"/brief/{chamber}/22"
    response = client.post(base + "/ask?preview=1", data={"choice": "snap_no_receipt"})
    assert response.status_code == 200
    identity = f"{chamber}:15:022:2022:below_poverty_no_snap:snap"
    tree = parse(response.text)
    card = tree.one("article", data_match=identity)
    brief = parse(client.get(base + "?preview=1").text).one("section", class_="matches")
    permalink = client.get(f"/match/{chamber}/22/snap/below_poverty_no_snap?preview=1")
    assert dom(card) == dom(brief.one("article", data_match=identity))
    assert dom(card) == dom(parse(permalink.text).one("article", data_match=identity))
    assert response.text.index("<p>") < response.text.index("<article")
    assert "Relevant need only" in card.text


def test_recorded_question_selects_same_card(
    matching_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    client = TestClient(app, client=("192.0.2.1", 1234))
    response = client.post(
        "/brief/house/22/ask?preview=1",
        data={"question": "Where could food-assistance outreach help here?"},
    )
    assert response.status_code == 200
    assert (
        parse(response.text).one("article").attrs["data-match"]
        == "house:15:022:2022:below_poverty_no_snap:snap"
    )


def test_nonmatch_answers_do_not_load_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    web = import_module("app.web.ask")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("nonmatch route must not read matches")

    monkeypatch.setattr(web, "find_matches", forbidden)
    response = TestClient(app, client=("192.0.2.1", 1234)).post(
        "/brief/house/22/ask?preview=1",
        data={"choice": "population"},
    )
    assert response.status_code == 200
    assert "data-match=" not in response.text


@pytest.mark.parametrize("width", [390, 768, 1440])
def test_ask_matches_have_no_serious_or_critical_axe_violations(
    page: Page, width: int, matching_store: Path
) -> None:
    client = TestClient(app, client=("192.0.2.1", 1234))
    brief = client.get("/brief/house/22?preview=1").text
    response = client.post("/brief/house/22/ask?preview=1", data={"choice": "snap_no_receipt"})
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(brief)
    page.locator("#ask-answer").evaluate("(node, html) => node.innerHTML = html", response.text)
    assert page.locator("#ask-answer article[data-match]").count() > 0
    root = Path(__file__).resolve().parents[2]
    for stylesheet in ("tokens.css", "site.css"):
        page.add_style_tag(path=str(root / "static" / stylesheet))
    assert axe_problems(page) == []


def test_known_ids_cannot_invent_an_unmapped_pair(matching_store: Path) -> None:
    from app.tools.matches import MatchReference, resolve_matches

    reference = MatchReference(district=DISTRICT, population_id="disability", program_id="snap")
    with pytest.raises(ValueError, match="unknown match reference"):
        resolve_matches(DISTRICT, (reference,))


@pytest.mark.parametrize("status,preview", [("off", True), ("preview", False)])
def test_hidden_matches_are_not_read_by_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, preview: bool
) -> None:
    from app import features

    config = tmp_path / "features.toml"
    config.write_text(f'outreach = "on"\nask = "on"\nmatches = "{status}"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", config)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("hidden matches must not be loaded")

    monkeypatch.setattr(import_module("app.web.ask"), "find_matches", forbidden)
    response = TestClient(app, client=("192.0.2.1", 1234)).post(
        "/brief/house/22/ask" + ("?preview=1" if preview else ""),
        data={"choice": "snap_no_receipt"},
    )
    assert response.status_code == 200
    assert "data-match=" not in response.text


@pytest.mark.parametrize("field", ["population_id", "program_id"])
@pytest.mark.parametrize("invalid", ["../snap", "snap?x=1", "snap#x", "snap%20", "snap\n"])
def test_match_identifiers_reject_untrusted_syntax(field: str, invalid: str) -> None:
    from app.tools.matches import MatchReference

    raw = {
        "district": DISTRICT.model_dump(),
        "population_id": "below_poverty_no_snap",
        "program_id": "snap",
        field: invalid,
    }
    with pytest.raises(ValidationError) as error:
        MatchReference.model_validate(raw)
    assert [e["loc"] for e in error.value.errors()] == [(field,)]


def test_match_store_failure_stays_an_operational_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.matches import find_matches

    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "missing.db"))
    with pytest.raises(FileNotFoundError, match="Matches fact store is missing"):
        find_matches(DISTRICT, "below_poverty_no_snap")
