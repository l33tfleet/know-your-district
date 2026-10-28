"""Pure presentation coordinates for already-loaded, published 90% intervals."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.models import Fact


@dataclass(frozen=True)
class IntervalMark:
    geography: str
    dot: float
    low: float | None
    high: float | None


def interval_layout(facts: Sequence[Fact | None]) -> list[IntervalMark]:
    """Map values and unclipped endpoints onto 0–100, including zero in the domain.

    Missing values have no marks; a missing MOE has a dot but no interval.
    Coordinates are presentation only and never estimates or comparison claims.
    """
    valued = [f for f in facts if f is not None and f.value is not None]
    endpoints = [0.0]
    for fact in valued:
        assert fact.value is not None
        margin = fact.moe if fact.moe is not None else 0
        endpoints.extend((fact.value - margin, fact.value + margin))
    low, high = min(endpoints), max(endpoints)
    span = high - low or 1.0

    def x(value: float) -> float:
        return (value - low) / span * 100

    marks: list[IntervalMark] = []
    for fact in valued:
        assert fact.value is not None
        marks.append(
            IntervalMark(
                fact.geography,
                x(fact.value),
                x(fact.value - fact.moe) if fact.moe is not None else None,
                x(fact.value + fact.moe) if fact.moe is not None else None,
            )
        )
    return marks
