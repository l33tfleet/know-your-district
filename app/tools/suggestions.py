"""Typed next-step proposals for one district, from the matching tool; no folder state.

A proposal names one match the tool offers the district now, its source and the date its program
record was last checked, and carries that match's #150 program card (county contacts with their
verification dates, the outreach email link, the official page and 211) for every band, not only
strong. Its words come from published records and `app/copy.yaml`, never from a model.

Decisions about proposals are kept by the folder store and read by `app/web/suggestions.py`; this
module never imports the folders, the agent or anything that sends email.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.program_cards import ProgramCard, program_cards
from app.tools.matches import DistrictMatches, MatchReference
from etl.boundaries import DistrictId

Source = Literal["district_matches"]


class Proposal(BaseModel):
    """One suggested next step; `source` and `dated` are required, never defaulted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    match: MatchReference
    source: Source
    dated: date
    card: ProgramCard


def propose(district: DistrictId) -> tuple[Proposal, ...]:
    """Every current match of the district, in the tool's ranked order; a missing store raises."""
    matches = DistrictMatches(district).get_matches()
    return tuple(
        Proposal(
            match=MatchReference(
                district=district, population_id=match.population.id, program_id=match.program.id
            ),
            source="district_matches",
            dated=match.program.last_verified,
            card=card,
        )
        for match, card in zip(matches, program_cards(district, matches), strict=True)
    )
