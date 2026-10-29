"""Derived population sums and shares from published cells; never written back as a `Fact`.

Each figure names its numerator cells, denominator cells and universe, and carries every
input `Fact` (table, vintage, geography) as derived provenance. Uncertainty follows the
Census Bureau approximations in the ACS handbook (`docs/data.md`, Reliability):

- sum: MOE = sqrt(MOE₁² + MOE₂² + …); a controlled MOE (annotation `*****`) counts as 0;
- proportion p = X / Y: MOE = sqrt(MOE_X² - p² · MOE_Y²) / Y, or the ratio formula
  sqrt(MOE_X² + p² · MOE_Y²) / Y when the proportion radicand is negative.

A missing cell or estimate leaves the figure unavailable and lists the missing cells; a
missing (not controlled) MOE leaves the MOE missing and the flag "use with caution". Cells
of different universes are never summed or divided.
"""

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.analysis.reliability import Reliability, classify
from app.models import Fact
from app.populations import TABLES, Population

CONTROLLED = "*****"
# A numerator universe wholly inside a broader denominator universe; mirrors
# `_WITHIN` in app/populations.py, which validates the registry entries against it.
SUBPOPULATION_OF = {
    "Native Hawaiian and Other Pacific Islander alone or in any combination": "Total population"
}


class Derived(BaseModel):
    """A derived count or share for one geography, with its inputs and uncertainty."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["sum", "share"]
    geography: str
    universe: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]
    value: float | None
    moe: float | None
    cv: float | None
    reliability: Reliability
    method: str
    inputs: tuple[Fact, ...]
    missing: tuple[str, ...]


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    geography: str
    count: Derived
    share: Derived


def _universe(cells: Sequence[str]) -> str:
    universes = {TABLES[cell.split("_")[0]][1] for cell in cells}
    if len(universes) != 1:
        raise ValueError(f"cells from different universes are never summed: {sorted(universes)}")
    return universes.pop()


def _flag(value: float | None, moe: float | None) -> tuple[float | None, Reliability]:
    cv, flag = classify(
        None if value is None else Decimal(repr(value)), None if moe is None else Decimal(repr(moe))
    )
    return (None if cv is None else float(cv)), flag


def total(cells: Sequence[str], geography: str, facts: Mapping[tuple[str, str], Fact]) -> Derived:
    """Sum published cells for one geography with the root-sum-of-squares MOE."""
    universe = _universe(cells)
    found = [facts.get((cell, geography)) for cell in cells]
    inputs = tuple(f for f in found if f is not None)
    missing = tuple(c for c, f in zip(cells, found, strict=True) if f is None or f.value is None)
    controlled = any(f.moe is None and f.moe_annotation == CONTROLLED for f in inputs)
    if len(cells) == 1:
        method = inputs[0].method if inputs else "published estimate and 90% margin of error"
    else:
        method = (
            f"derived: sum of {len(cells)} published estimates; "
            "MOE sqrt(MOE₁² + MOE₂² + …) (Census approximation)"
        )
    if controlled:
        method += "; a controlled MOE counts as 0"
    value = moe = None
    if not missing:
        value = math.fsum(f.value for f in inputs if f.value is not None)
        moes = [0.0 if f.moe is None and f.moe_annotation == CONTROLLED else f.moe for f in inputs]
        if all(m is not None for m in moes):
            moe = math.sqrt(math.fsum(m * m for m in moes if m is not None))
    cv, flag = _flag(value, moe)
    return Derived(
        kind="sum",
        geography=geography,
        universe=universe,
        numerator=tuple(cells),
        denominator=(),
        value=value,
        moe=moe,
        cv=cv,
        reliability=flag,
        method=method,
        inputs=inputs,
        missing=missing,
    )


def share(numerator: Derived, denominator: Derived) -> Derived:
    """Percentage share of two sums of the same universe (ACS handbook proportion MOE)."""
    if numerator.geography != denominator.geography:
        raise ValueError("a share divides sums for one geography")
    nested = SUBPOPULATION_OF.get(numerator.universe) == denominator.universe
    if numerator.universe != denominator.universe and not nested:
        raise ValueError(
            f"never divide cells from different universes: {numerator.universe!r} "
            f"over {denominator.universe!r}"
        )
    seen: set[tuple[str, str]] = set()
    inputs: list[Fact] = []
    for f in numerator.inputs + denominator.inputs:
        if (f.variable, f.geography) not in seen:
            seen.add((f.variable, f.geography))
            inputs.append(f)
    missing = tuple(dict.fromkeys(numerator.missing + denominator.missing))
    method = "derived: proportion of published estimates; MOE ACS handbook proportion formula"
    value = moe = None
    x, y = numerator.value, denominator.value
    if x is not None and y is not None:
        if y == 0:
            method = "derived: not computed, the denominator is zero"
        else:
            p = x / y
            value = p * 100
            if numerator.moe is not None and denominator.moe is not None:
                radicand = numerator.moe**2 - p**2 * denominator.moe**2
                if radicand < 0:
                    radicand = numerator.moe**2 + p**2 * denominator.moe**2
                    method = (
                        "derived: proportion of published estimates; MOE ACS handbook ratio "
                        "formula (the proportion formula's radicand is negative)"
                    )
                moe = math.sqrt(radicand) / y * 100
    cv, flag = _flag(value, moe)
    return Derived(
        kind="share",
        geography=numerator.geography,
        universe=denominator.universe,
        numerator=numerator.numerator,
        denominator=denominator.numerator,
        value=value,
        moe=moe,
        cv=cv,
        reliability=flag,
        method=method,
        inputs=tuple(inputs),
        missing=missing,
    )


def compare(
    population: Population, geographies: Sequence[str], facts: Mapping[tuple[str, str], Fact]
) -> tuple[Comparison, ...]:
    """The population's count and share in each geography, in the order given."""
    results: list[Comparison] = []
    for geography in geographies:
        count = total(population.numerator, geography, facts)
        base = total(population.denominator, geography, facts)
        if base.universe != population.universe:
            raise ValueError(f"{population.id}: denominator universe is {base.universe!r}")
        results.append(Comparison(geography=geography, count=count, share=share(count, base)))
    return tuple(results)
