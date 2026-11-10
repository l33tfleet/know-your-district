"""Suggestion references for tools: no folder id, note or figure; `store.py` keeps decisions."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.folders.references import decode_match
from app.tools.matches import MatchReference

Decision = Literal["accepted", "dismissed"]


class SuggestionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    match: MatchReference
    source: Literal["district_matches"]
    dated: date


class SuggestionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: SuggestionReference
    decision: Decision
    card_id: int | None  # the match's live card, its next step; always set once accepted
    created_at: str
    updated_at: str


def from_row(row: dict[str, Any]) -> SuggestionDecision:
    """A stored key that is not a match key leaves `match` None, which validation refuses."""
    match = decode_match(row["suggestion_key"], row["chamber"], row["district"])
    reference = {"match": match, "source": row["source"], "dated": row["dated"]}
    fields = ("decision", "card_id", "created_at", "updated_at")
    return SuggestionDecision.model_validate({"reference": reference} | {f: row[f] for f in fields})
