"""#220: shared opening-case content and detached evidence survive adaptation."""

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

from app.analysis.matching import score_match
from app.analysis.populations import compare
from app.cases import case
from app.models import Fact
from app.populations import load_populations
from app.snap import SnapResult, load_result
from app.tools.matches import ProgramMatch
from etl.boundaries import DistrictId
from etl.programs import load_catalog
from etl.programs.mappings import load_mappings

ROOT = Path(__file__).resolve().parents[2]


def test_shared_partial_keeps_wording_out_of_template() -> None:
    source = (ROOT / "templates/partials/match_card.html").read_text()
    source = re.sub(r"{#.*?#}|{%.*?%}|{{.*?}}", " ", source, flags=re.S)
    source = re.sub(r"<!--.*?-->|<[^>]*>|&[a-z]+;", " ", source, flags=re.S)
    assert not re.search(r"[^\W\d_]", source)


def example(*, missing: bool = False, caution: bool = False) -> tuple[ProgramMatch, SnapResult]:
    outreach = load_result(DistrictId(chamber="house", district=22))
    population = next(p for p in load_populations().populations if p.id == "below_poverty_no_snap")
    program = next(p for p in load_catalog(ROOT / "data/programs.yaml") if p.id == "snap")
    mapping = next(m for m in load_mappings() if m.program_id == program.id)
    facts: dict[tuple[str, str], Fact] = {}
    fact = outreach.district.fact
    assert fact is not None
    if not missing:
        if caution:
            fact = Fact.model_validate(
                fact.model_dump() | {"moe": None, "cv": None, "reliability": "caution"}
            )
        facts[fact.variable, fact.geography] = fact
    (count,) = compare(population, (outreach.district.geography,), facts)
    match = ProgramMatch(
        population=population,
        program=program,
        mapping=mapping,
        count=count.count,
        result=score_match(mapping, population, count.share),
    )
    return match, outreach


def render(card: object) -> str:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())
    return env.get_template("partials/match_card.html").render(card=card)


def test_complete_card_preserves_identity_evidence_and_opening_case() -> None:
    from app.match_cards import to_match_card

    match, outreach = example()
    record = case("snap_no_receipt")
    before = match.model_dump()
    card = to_match_card(match, outreach=outreach, record=record)
    assert card == to_match_card(match, outreach=outreach, record=record)
    assert match.model_dump() == before
    assert card.id == "house:15:022:2022:below_poverty_no_snap:snap"
    assert (card.program_id, card.population_id, card.case_id) == (
        "snap",
        record.population,
        record.id,
    )
    assert card.figure is match.count
    assert card.figure.inputs[0] is match.count.inputs[0]
    assert card.reason == match.result.reason
    assert card.band == match.result.band
    assert card.claim == match.result.claim
    assert card.review_status == match.mapping.review_status
    page = render(card)
    for text in (
        match.program.name,
        match.program.agency,
        match.population.label,
        match.population.universe,
        match.mapping.relevance,
        record.claim,
        record.failure.note,
        "What we know",
        "What we don't",
        "Next step",
        "Relevant need only",
        "pending",
        "agency decides eligibility",
        "Aloha United Way 211",
        str(match.program.official_url),
        outreach.undercount_note,
        outreach.poverty_note,
        outreach.referral_note,
        "County/state context",
    ):
        # Apostrophes and ampersands are escaped at the HTML boundary.
        from html import unescape

        assert text in unescape(page)
    for reading in outreach.counties:
        assert reading.geography in page
    for fact in card.figure.inputs:
        for text in (
            fact.variable,
            fact.table_id,
            fact.source,
            fact.vintage,
            fact.geography,
            fact.method,
            str(fact.value),
            str(fact.moe),
            fact.endpoint,
        ):
            assert text in page
    assert outreach.referral is not None
    assert str(outreach.referral.outreach_url) in page
    with pytest.raises(ValidationError):
        card.program_name = "changed"
    match.program.name = "changed upstream"
    assert card.program_name != match.program.name


@pytest.mark.parametrize("missing,caution", [(True, False), (False, True)])
def test_missing_or_uncertain_evidence_stays_visible(missing: bool, caution: bool) -> None:
    from app.match_cards import to_match_card

    match, _ = example(missing=missing, caution=caution)
    card = to_match_card(match)
    page = render(card)
    assert "Official program information" in page
    assert "Aloha United Way 211" in page
    assert "County next steps not documented" in page
    assert "Comparable uptake unavailable" in page
    if missing:
        assert "Not available" in page
        assert "B22003_006E" in page
        assert "insufficient" in page
    else:
        assert "use with caution" in page
        assert "Margin of error unavailable" in page


def test_untrusted_prose_is_escaped_and_wrong_evidence_is_rejected() -> None:
    from app.match_cards import to_match_card

    match, outreach = example()
    match.program.name = '<img src=x onerror="alert(1)">'
    page = render(to_match_card(match))
    assert "<img" not in page
    assert "&lt;img" in page
    wrong = outreach.model_copy(
        update={"district": outreach.district.model_copy(update={"geography": "house:15:001:2022"})}
    )
    with pytest.raises(ValueError, match="outreach"):
        to_match_card(match, outreach=wrong)
    wrong_record = case("snap_no_receipt").model_copy(update={"population": "disability"})
    with pytest.raises(ValueError, match="case"):
        to_match_card(match, record=wrong_record)


def test_adapter_needs_only_detached_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.match_cards import to_match_card

    match, outreach = example()
    record = case("snap_no_receipt")

    def no_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("adapter must not read storage")

    monkeypatch.setattr(Path, "read_text", no_read)
    card = to_match_card(match, outreach=outreach, record=record)
    assert card.outreach is outreach
    assert set(record.known.values()) <= {text for _, text in card.known}
    assert set(record.unknown.values()) <= {text for _, text in card.unknown}
