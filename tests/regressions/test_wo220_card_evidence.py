"""#220: optional evidence must belong to the card's program."""

import pytest
from pydantic import HttpUrl

from app.cases import case
from app.match_cards import to_match_card
from etl.programs import load_catalog
from tests.regressions.test_wo152_card import ROOT, example


def test_snap_outreach_rejected_for_other_program_in_same_district() -> None:
    match, outreach = example()
    program = next(p for p in load_catalog(ROOT / "data/programs.yaml") if p.id != "snap")
    match = match.model_copy(update={"program": program})
    assert outreach.district.geography == match.count.geography
    assert to_match_card(match).program_id == program.id

    with pytest.raises(ValueError, match=r"^outreach evidence must match the SNAP card district$"):
        to_match_card(match, outreach=outreach)


def test_case_rejected_for_different_program_url_with_same_population() -> None:
    match, _ = example()
    record = case("snap_no_receipt")
    assert record.population == match.population.id
    assert to_match_card(match, record=record).case_id == record.id
    record = record.model_copy(
        update={
            "program": record.program.model_copy(
                update={"url": HttpUrl("https://example.org/different-program")}
            )
        }
    )

    with pytest.raises(ValueError, match=r"^case evidence must match the population and program$"):
        to_match_card(match, record=record)
