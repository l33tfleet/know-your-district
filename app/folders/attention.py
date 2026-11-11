"""Deterministic office next steps over saved records, shared by the page and future tools.

No reads, writes, model calls or figures. Dates use the store's UTC calendar days. Without
a note, the case's creation day starts the follow-up clock; changing status or priority
does not stand in for an outreach note. Only live cards and notes belong in the inputs.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.folders.store import Card, Note

PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


@dataclass(frozen=True)
class Attention:
    case: Card
    next_step: str
    reason: str


def elapsed(days: int) -> str:
    return f"{days} day" if days == 1 else f"{days} days"


def needs_attention(cards: Sequence[Card], notes: Sequence[Note], today: date) -> list[Attention]:
    """First contact, then overdue follow-up, then priority and oldest saved change.

    Completed cases are omitted. Other active cases stay visible for review even when
    neither urgent rule applies. A saved priority reason is quoted, never interpreted.
    """
    ranked: list[tuple[int, Attention]] = []
    for card in cards:
        if card.status == "done":
            continue
        age = (today - datetime.fromisoformat(card.created_at).date()).days
        changed = (today - datetime.fromisoformat(card.updated_at).date()).days
        latest = max((note.dated for note in notes if note.card_id == card.id), default=None)
        quiet = (today - date.fromisoformat(latest)).days if latest else age
        activity = (
            f"{elapsed(quiet)} since the last note"
            if latest
            else f"no notes, saved {elapsed(age)} ago"
        )
        priority = card.priority.capitalize()
        if card.priority == "high" and card.status == "idea":
            rank, step = 0, "Make first contact"
            reason = f"High priority, still an idea, saved {elapsed(age)} ago."
        elif card.status in ("contacted", "planned") and quiet >= 14:
            rank, step = 1, "Follow up"
            reason = f"{priority} priority, status {card.status}, {activity}."
        else:
            rank, step = 2, "Review next step"
            reason = (
                f"{priority} priority, status {card.status}, "
                f"changed {elapsed(changed)} ago. {activity}."
            )
        if card.reason:
            reason += f" Saved priority reason: {card.reason}"
        ranked.append((rank, Attention(case=card, next_step=step, reason=reason)))
    ranked.sort(
        key=lambda entry: (
            entry[0],
            PRIORITY_ORDER[entry[1].case.priority],
            datetime.fromisoformat(entry[1].case.updated_at),
            entry[1].case.id,
        )
    )
    return [item for _, item in ranked]
