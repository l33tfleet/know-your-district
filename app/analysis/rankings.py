"""Order published district figures and say whether the top of the order is firm; no wording."""

from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from app.models import Fact

TOP = 5


class Ranking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ranked: tuple[tuple[str, Fact], ...]
    left_out: int
    overlaps: bool

    @property
    def top(self) -> tuple[tuple[str, Fact], ...]:
        return self.ranked[:TOP]


def _overlap(a: Fact, b: Fact) -> bool:
    """Published margins that touch or cross; a missing margin cannot show a difference."""
    assert a.value is not None and b.value is not None
    if a.moe is None or b.moe is None:
        return True
    difference = abs(Decimal(str(a.value)) - Decimal(str(b.value)))
    return difference <= Decimal(str(a.moe)) + Decimal(str(b.moe))


def rank(facts: dict[str, Fact | None], descending: bool) -> Ranking:
    """Rows with a published value, in order, by district number; ties keep the input order."""
    published = [(n, fact) for n, fact in facts.items() if fact and fact.value is not None]
    ranked = sorted(published, key=lambda item: item[1].value or 0.0, reverse=descending)
    top = [fact for _, fact in ranked[:TOP]]
    return Ranking(
        ranked=tuple(ranked),
        left_out=len(facts) - len(published),
        overlaps=any(_overlap(a, b) for a, b in pairwise(top)),
    )
