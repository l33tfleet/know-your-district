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
    "relevant_need": "Relevant need only — a group to reach",
    "modeled_eligibility": "Model of who may meet the rules. The agency must check",
    "comparable_nonparticipation": "Matched counts estimate how many meet the rules but lack aid",
}

# Mirrors the opening case labels in app/copy.yaml; adaptation performs no I/O.
GAPS = {
    "unused_appropriation": "Unused funds",
    "eligible_nonparticipation": "May not be signed up",
    "application_or_renewal_barrier": "Hard to apply or renew",
    "underpayment": "Paid too little",
    "redemption_or_expiration_loss": "Benefits not used or lost",
    "service_capacity_or_fit": "Service is full or a poor fit",
}
ACTIONS = {
    "targeted_information": "Share facts with the group",
    "navigator_referral": "Refer to a helper",
    "outreach_planning_lead": "Outreach-planning lead",
    "agency_follow_up": "Agency follow-up",
}


class CardWording(BaseModel):
    """Detached display labels so the shared partial contains no prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    survey: str = "Survey population: the group we could reach."
    not_available: str = "Not available for this count"
    moe: str = "90% margin of error"
    no_moe: str = "Margin of error unavailable. The survey gives no range"
    unavailable: str = "no range given"
    missing: str = "Missing count"
    method: str = "Method"
    gap: str = "Kind of gap"
    action: str = "Action"
    review: str = "Program-expert review"
    band: str = "Outreach band"
    known: str = "What we know"
    unknown: str = "What we don't"
    none_documented: str = "No facts on file."
    next_step: str = "Next step"
    official: str = "Official program information: read the steps to get help"
    referral: str = "Aloha United Way 211"
    county: str = "County/state context"
    outreach: str = "DHS SNAP outreach providers"
    checked: str = "Checked"
    no_county_steps: str = "County next steps not documented. Ask the state for help. Use the official program page or 211."


class MatchCard(BaseModel):
    """Immutable snapshot: no mutable catalog records or case dictionaries retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    wording: CardWording = CardWording()
    id: str
    case_id: str | None
    program_id: str
    program_name: str
    agency: str
    population_id: str
    population: str
    definition: str
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
    known = tuple(("What we see", text) for text in mapping.observed_conditions)
    unknown = tuple(("What we still need to know", text) for text in mapping.unobserved_conditions)
    links: tuple[tuple[str, HttpUrl], ...] = ()
    steps = tuple(p.next_steps.instructions) if p.next_steps else ()
    if p.next_steps:
        links += (("Get help with the program", p.next_steps.contact.url),)
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
        definition=population.definition,
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
        disclaimer="The program may help. The agency decides eligibility. "
        "Bands rank groups to reach. They are not the odds that a person meets the rules.",
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
