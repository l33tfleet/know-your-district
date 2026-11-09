"""Versioned selection keys in schema v1; no figures are persisted.

Legacy case keys stay unchanged. Match keys use a reserved colon namespace;
chamber and district remain in their existing card columns. Callers resolve the
returned reference through the matching tool afresh before showing figures.
Rollback: stop match writes and soft-delete match cards through an operator
migration before reverting consumers; legacy cards, notes and links need no migration.
"""

import re

from app.tools.matches import MatchReference
from etl.boundaries import Chamber, DistrictId

_MATCH_KEY = re.compile(r"match:v1:([a-z][a-z0-9_]*):([a-z][a-z0-9]*(?:-[a-z0-9]+)*)")


def encode_match(reference: MatchReference) -> str:
    """Encode a validated selection without changing its district or program identity."""
    return f"match:v1:{reference.population_id}:{reference.program_id}"


def decode_match(key: str, chamber: Chamber, district: int) -> MatchReference | None:
    """Return None for a legacy key; malformed/version-unknown match keys fail loudly."""
    if ":" not in key:
        return None
    match = _MATCH_KEY.fullmatch(key)
    if match is None:
        raise ValueError("Invalid match key; expected match:v1:<population_id>:<program_id>")
    return MatchReference(
        district=DistrictId(chamber=chamber, district=district),
        population_id=match[1],
        program_id=match[2],
    )
