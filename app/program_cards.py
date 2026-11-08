"""Strong outreach cards, adapted from detached tools without changing their ranking.

County overlays select service areas only; neither area shares nor contact presence
establish a physical office, eligibility, appointments or capacity. Expanded evidence
is screen-only in the brief; the same partial can render an optional email excerpt.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, HttpUrl

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
    wording: ProgramCardWording = ProgramCardWording()


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
            match=to_match_card(match),
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
