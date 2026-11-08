"""Detached shared case cards; pure adaptation of prerequisite tool results.

The opening case's figure/understand/evidence/next-step layout is shared here.
Routing and brief/Ask integration belong to subsequent work orders.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl

from app.analysis.matching import Band
from app.analysis.populations import Derived
from app.analysis.reliability import FLAG_WORDS
from app.cases import PROBLEMS, Case
from app.snap import SnapResult
from app.tools.matches import ProgramMatch

CLAIMS = {
    "relevant_need": "Relevant need only — potential outreach audience",
    "modeled_eligibility": "Modeled eligibility — agency confirmation required",
    "comparable_nonparticipation": "Comparable nonparticipation — aggregate estimate",
}

# Mirrors the opening case labels in app/copy.yaml; adaptation performs no I/O.
GAPS = {
    "unused_appropriation": "Unused appropriation",
    "eligible_nonparticipation": "Possible nonparticipation",
    "application_or_renewal_barrier": "Application or renewal barrier",
    "underpayment": "Underpayment",
    "redemption_or_expiration_loss": "Redemption or expiration loss",
    "service_capacity_or_fit": "Service capacity or fit",
}
ACTIONS = {
    "targeted_information": "Targeted information",
    "navigator_referral": "Navigator referral",
    "outreach_planning_lead": "Outreach-planning lead",
    "agency_follow_up": "Agency follow-up",
}


class MatchCard(BaseModel):
    """Immutable snapshot: no mutable catalog records or case dictionaries retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    case_id: str | None
    program_id: str
    program_name: str
    agency: str
    population_id: str
    population: str
    unit: str
    universe: str
    exclusions: tuple[str, ...]
    figure: Derived
    reliability_word: str
    reason: str
    band: Band
    claim: Literal["relevant_need", "modeled_eligibility", "comparable_nonparticipation"]
    claim_label: str
    review_status: Literal["pending", "reviewed", "rejected"]
    official_url: HttpUrl
    referral_url: HttpUrl
    disclaimer: str
    known: tuple[tuple[str, str], ...]
    unknown: tuple[tuple[str, str], ...]
    case_claim: str
    gap: str
    action: str
    checked: str
    links: tuple[tuple[str, HttpUrl], ...]
    next_steps: tuple[str, ...]
    outreach: SnapResult | None


def to_match_card(
    match: ProgramMatch, *, outreach: SnapResult | None = None, record: Case | None = None
) -> MatchCard:
    """Snapshot a validated match without reading storage or recalculating figures.

    Optional SNAP evidence reuses the detached outreach adapter and preserves all
    county contexts, contact limitations and verification dates. Absence stays explicit.
    """
    p, population, mapping, result = match.program, match.population, match.mapping, match.result
    if outreach is not None and (
        p.id != "snap" or outreach.district.geography != match.count.geography
    ):
        raise ValueError("outreach evidence must match the SNAP card district")
    if record is not None and (
        record.population != population.id or record.program.url != p.official_url
    ):
        raise ValueError("case evidence must match the population and program")
    known = tuple(("Observed condition", text) for text in mapping.observed_conditions)
    unknown = tuple(("Unobserved condition", text) for text in mapping.unobserved_conditions)
    links: tuple[tuple[str, HttpUrl], ...] = ()
    steps = tuple(p.next_steps.instructions) if p.next_steps else ()
    if p.next_steps:
        links += (("Program assistance", p.next_steps.contact.url),)
    if record:
        known += tuple(
            (key.capitalize(), record.known[key]) for key in PROBLEMS if key in record.known
        )
        unknown += tuple(
            (key.capitalize(), record.unknown[key]) for key in PROBLEMS if key in record.unknown
        )
        links += tuple((link.label, link.url) for link in record.action.links)
    return MatchCard(
        id=f"{match.count.geography}:{population.id}:{p.id}",
        case_id=record.id if record else None,
        program_id=p.id,
        program_name=p.name,
        agency=p.agency,
        population_id=population.id,
        population=population.label,
        unit=population.unit,
        universe=population.universe,
        exclusions=population.exclusions,
        figure=match.count,
        reliability_word=FLAG_WORDS[match.count.reliability],
        reason=result.reason,
        band=result.band,
        claim=result.claim,
        claim_label=CLAIMS[result.claim],
        review_status=mapping.review_status,
        official_url=p.official_url,
        referral_url=HttpUrl(p.referral_url),
        disclaimer="Program may help; the agency decides eligibility. "
        "Bands rank outreach signals; they are not eligibility probabilities.",
        known=known,
        unknown=unknown,
        case_claim=record.claim if record else mapping.relevance,
        gap=f"{GAPS[record.failure.gap]} ({record.failure.note})" if record else "",
        action=ACTIONS[record.action.kind] if record else "",
        checked=f"Rule source checked {record.program.rule_checked if record else p.last_verified}.",
        links=links,
        next_steps=steps,
        outreach=outreach,
    )
