"""Strong outreach cards, adapted from detached tools without changing their ranking.

County overlays select service areas only; neither area shares nor contact presence
establish a physical office, eligibility, appointments or capacity. Expanded evidence
is screen-only in the brief; the same partial can render an optional email excerpt.
"""

from datetime import date
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, HttpUrl

from app.analysis.populations import Derived
from app.analysis.reliability import FLAG_WORDS
from app.copy import geography_name, load_copy
from app.counties import load_mapping
from app.match_cards import MatchCard, to_match_card
from app.program_contacts import load_contacts
from app.tools.matches import DistrictMatches
from etl.boundaries import DistrictId
from etl.programs.contracts import load_organisations


class CardContact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: str
    url: HttpUrl
    verified_on: date


class CountyContacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    geography: str
    name: str
    contacts: tuple[CardContact, ...]


class ProgramCardWording(BaseModel):
    """Detached display labels, following the shared MatchCard wording adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outreach_email: str = "Ask the agency about outreach here"
    evidence: str = "Reason, uncertainty and cited evidence"
    source_table: str = "Source table"
    service_areas: str = (
        "County service areas only; contact listings do not establish local offices, "
        "appointments or capacity."
    )
    verified: str = "Verified"
    missing_contacts: str = (
        "County contacts not documented. Use official program information or Aloha United Way 211."
    )


class ProgramCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    match: MatchCard
    guidance: str
    counties: tuple[CountyContacts, ...]
    screen_only: str
    email_url: str
    wording: ProgramCardWording = ProgramCardWording()


def _outreach_email(
    district: DistrictId, card: MatchCard, guidance: str, figures: tuple[Derived, ...]
) -> str:
    """Serialize detached public evidence only; no recipient or request context."""
    district_name = f"Hawaiʻi State {district.chamber.title()} District {district.district}"
    subject = f"Outreach inquiry: {district_name} · {card.program_name}"
    lines = [
        f"Ask the agency about outreach here: {district_name}",
        f"Program: {card.program_name}",
        f"Agency: {card.agency}",
        f"Population: {card.population}",
        card.definition,
        f"Universe: {card.universe}",
        card.claim_label,
        f"{card.wording.review}: {card.review_status}",
        f"{card.wording.band}: {card.band}",
        card.case_claim,
        card.reason,
        *card.exclusions,
    ]
    for index, figure in enumerate((card.figure, *figures)):
        value = (
            f"{figure.value} {card.unit if index == 0 or figure.kind == 'sum' else '%'}"
            if figure.value is not None
            else card.wording.not_available
        )
        uncertainty = (
            f"{card.wording.moe} ±{figure.moe}" if figure.moe is not None else card.wording.no_moe
        )
        lines.extend(
            [
                f"{value}; {uncertainty}; {FLAG_WORDS[figure.reliability]}.",
                f"{figure.geography} · {figure.universe} · {figure.method}",
            ]
        )
        if figure.missing:
            lines.append(f"{card.wording.missing}: {', '.join(figure.missing)}")
        for fact in figure.inputs:
            lines.append(
                f"{fact.source}, {fact.table_id}, {fact.variable}, {fact.vintage}, "
                f"{fact.geography}. {card.wording.method}: {fact.method}. {fact.endpoint}"
            )
    lines.extend(
        [
            f"{card.wording.known}: " + " ".join(text for _, text in card.known),
            f"{card.wording.unknown}: " + " ".join(text for _, text in card.unknown),
            card.disclaimer,
            guidance,
            f"{card.wording.official}: {card.official_url}",
            f"{card.wording.referral}: {card.referral_url}",
            card.checked,
            *card.next_steps,
            *(f"{label}: {url}" for label, url in card.links),
            f"Brief: https://district.hawaiitechmentors.org/brief/{district.chamber}/{district.district}",
        ]
    )
    return "mailto:?" + urlencode({"subject": subject, "body": "\n".join(lines)}, quote_via=quote)


def load_cards(district: DistrictId) -> tuple[ProgramCard, ...]:
    """Read only when enabled, retaining tool order and every mapped county."""
    ranked = DistrictMatches(district).get_matches()
    counties = load_mapping()[district.fact_key]
    contacts = load_contacts()
    organisations = load_organisations()
    screen_only = load_copy()["brief"]["screen_only"]
    return tuple(
        ProgramCard(
            screen_only=screen_only,
            match=(card := to_match_card(match)),
            email_url=_outreach_email(district, card, match.program.guidance, match.result.figures),
            guidance=match.program.guidance,
            counties=tuple(
                CountyContacts(
                    geography=county.county,
                    name=geography_name(county.county),
                    contacts=tuple(
                        CardContact(
                            name=organisations[c.organisation_id].name,
                            kind="Agency office information"
                            if c.kind == "agency_office"
                            else "Partner",
                            url=c.url,
                            verified_on=c.verified_on,
                        )
                        for c in contacts
                        if c.program_id == match.program.id
                        and c.county == county.county.rsplit(":", 1)[1]
                    ),
                )
                for county in counties
            ),
        )
        for match in ranked
        if match.result.band == "strong"
    )
