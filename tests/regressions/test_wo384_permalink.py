"""#384: isolate permalink rejection branches and preserve prerequisite lineage."""

import sqlite3
from html import unescape
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.match_cards import to_match_card
from app.page_state import page_state
from app.tools.matches import DistrictMatches
from etl.programs.mappings import load_mappings
from tests.regressions.test_wo149_matches import matching_store

__all__ = ["matching_store"]
PATH = "/match/house/22/snap/below_poverty_no_snap?preview=1"


@pytest.mark.parametrize(
    "path,last_check",
    [
        (PATH.replace("preview=1", "preview=bad"), "page_state"),
        (PATH.replace("house/22", "house/52"), "require_feature"),
        (PATH.replace("/snap/", "/unknown/"), "load_populations"),
        (PATH.replace("/below_poverty_no_snap", "/unknown"), "load_mappings"),
        (PATH.replace("/below_poverty_no_snap", "/disability"), "DistrictMatches"),
    ],
    ids=[
        "invalid-preview",
        "invalid-district",
        "unknown-program",
        "unknown-population",
        "unmapped",
    ],
)
def test_rejection_stops_at_its_own_boundary(path: str, last_check: str) -> None:
    """All earlier checks accept; reaching the next dependency is itself a failure."""
    route = import_module("app.web.matches")
    with patch.object(route, last_check, side_effect=AssertionError("read after rejection")):
        response = TestClient(app).get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Page not found</h1>" in response.text
    assert 'data-match="' not in response.text


def test_rejected_mapping_is_not_an_unmapped_pair() -> None:
    """Supply the exact valid pair, rejected solely by its review status."""
    route = import_module("app.web.matches")
    mapping = next(
        m
        for m in load_mappings()
        if m.program_id == "snap" and m.population_id == "below_poverty_no_snap"
    ).model_copy(update={"review_status": "rejected"})
    with (
        patch.object(route, "load_mappings", return_value=(mapping,)),
        patch.object(route, "DistrictMatches", side_effect=AssertionError("rejected review")),
    ):
        response = TestClient(app).get(PATH)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Page not found</h1>" in response.text
    assert 'data-match="' not in response.text


def test_empty_matching_result_is_404() -> None:
    """An active, mapped pair can still have no prerequisite matching result."""
    with patch.object(DistrictMatches, "get_matches", autospec=True, return_value=()) as get:
        response = TestClient(app).get(PATH)
    assert get.call_count == 1
    selected = get.call_args.args[1]
    assert len(selected) == 1
    assert selected[0].program_id == "snap"
    assert selected[0].population_id == "below_poverty_no_snap"
    assert selected[0].review_status != "rejected"
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Page not found</h1>" in response.text
    assert 'data-match="' not in response.text


@pytest.mark.parametrize("error", [FileNotFoundError("missing fact store"), RuntimeError("bug")])
def test_matching_failure_does_not_publish_a_missing_card(error: Exception) -> None:
    with (
        patch.object(DistrictMatches, "get_matches", autospec=True, side_effect=error),
        pytest.raises(type(error), match=str(error)),
    ):
        TestClient(app).get(PATH)


@pytest.mark.parametrize("chamber", ["house", "senate"])
@pytest.mark.parametrize("band", ["strong", "possible"])
def test_permalink_preserves_original_projection_and_fact_lineage(
    chamber: str, band: str, matching_store: Path
) -> None:
    if band == "possible":
        # Equal shares remove the district's prominence, leaving a possible signal.
        with sqlite3.connect(matching_store) as db:
            db.execute(
                "UPDATE facts SET value = 42 WHERE geography = 'state:15' "
                "AND variable = 'B22003_006E'"
            )
    state = page_state(chamber, "22", preview=True)
    assert state is not None
    mapping = next(
        m
        for m in load_mappings()
        if m.program_id == "snap" and m.population_id == "below_poverty_no_snap"
    )
    match = DistrictMatches(state.district).get_matches((mapping,))[0]
    card = to_match_card(match)
    assert card.figure == match.count
    assert card.reason == match.result.reason
    assert card.band == match.result.band == band
    assert card.claim == match.result.claim
    assert card.review_status == mapping.review_status
    steps = match.program.next_steps
    assert card.next_steps == (tuple(steps.instructions) if steps else ())
    assert card.official_url == match.program.official_url
    assert str(card.referral_url) == match.program.referral_url
    response = TestClient(app).get(PATH.replace("house", chamber))
    assert response.status_code == 200
    article = unescape(response.text).split('<article class="case"', 1)[1].split("</article>")[0]
    for text in (
        card.agency,
        card.population,
        card.reason,
        card.claim_label,
        f"Program-expert review: {card.review_status}",
        f"Outreach band: {card.band}",
        card.disclaimer,
        str(card.official_url),
        str(card.referral_url),
        *card.next_steps,
    ):
        assert text in article
    assert card.figure.inputs
    for fact in card.figure.inputs:
        for text in (
            fact.variable,
            fact.source,
            fact.table_id,
            fact.vintage,
            fact.geography,
            fact.method,
            str(fact.endpoint),
        ):
            assert text in article


def test_permalink_keeps_documented_program_next_steps(matching_store: Path) -> None:
    state = page_state("house", "22", preview=True)
    assert state is not None
    mapping = next(
        m
        for m in load_mappings()
        if m.program_id == "hawaii-able" and m.population_id == "disability"
    )
    match = DistrictMatches(state.district).get_matches((mapping,))[0]
    assert match.program.next_steps is not None
    card = to_match_card(match)
    assert card.next_steps == tuple(match.program.next_steps.instructions)
    assert card.next_steps
    response = TestClient(app).get("/match/house/22/hawaii-able/disability?preview=1")
    assert response.status_code == 200
    article = unescape(response.text).split('<article class="case"', 1)[1].split("</article>")[0]
    for instruction in card.next_steps:
        assert instruction in article
    assert str(match.program.next_steps.contact.url) in article
