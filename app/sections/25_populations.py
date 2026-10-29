# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Populations from the registry (`data/populations.yaml`): each one's count and share in the
district beside its county and state, derived from published cells with the MOE, reliability
in words, numerator, denominator, universe and every input cell's citation.

Off until `features.toml` turns `populations` on: the fact table does not carry these cells yet,
and a missing cell shows as "not available", never as zero."""

from collections.abc import Callable

from app.analysis.populations import Derived, compare
from app.analysis.reliability import FLAG_WORDS
from app.copy import geography_name
from app.counties import load_mapping
from app.facts import FactStore, acs_config
from app.page_state import PageState
from app.populations import load_populations

FEATURE = "populations"
STATE = "state:15"
# Wording lives here, not in the template (#97); app/copy.yaml is outside this work order.
WORDS = {
    "heading": "Who lives here: populations compared with county and state",
    "intro": (
        "Counts and shares are derived from published {source} {vintage} cells. A share uses "
        "the same numerator and denominator in every geography; a cell that is not published "
        "shows as not available."
    ),
    "caption": ": district, county and state",
    "geography": "Geography",
    "count": "Count",
    "share": "Share of",
    "summary": "Source and derivation",
    "universe": "Universe",
    "excluded": "Excluded",
    "numerator": "Numerator cells",
    "denominator": "Denominator cells",
    "count_method": "Count method",
    "share_method": "Share method",
    "missing": "Not available",
    "inputs": "Input cells",
    "table": ", table",
    "not_available": "not available",
}


def _count(value: float) -> str:
    return f"{value:,.0f}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


def _points(value: float) -> str:
    return f"{value:.1f} percentage points"


def _reading(
    figure: Derived, fmt: Callable[[float], str], moe_fmt: Callable[[float], str]
) -> dict[str, object]:
    return {
        "found": figure.value is not None,
        "value": figure.value,
        "value_text": WORDS["not_available"] if figure.value is None else fmt(figure.value),
        "moe": figure.moe,
        "moe_text": "no margin of error" if figure.moe is None else "±" + moe_fmt(figure.moe),
        "reliability": figure.reliability,
        "word": FLAG_WORDS[figure.reliability],
        "method": figure.method,
        "missing": figure.missing,
    }


def context(state: PageState) -> dict[str, object]:
    registry = load_populations()
    vintage, _ = acs_config()
    district = state.district.fact_key
    counties = [share.county for share in load_mapping()[district]]
    cells = {cell for p in registry.populations for cell in p.numerator + p.denominator}
    geographies = (district, *counties, STATE)
    facts = FactStore.default().get(((c, g) for c in cells for g in geographies), vintage)
    populations: list[dict[str, object]] = []
    for population in registry.populations:
        shown = (
            district,
            *(counties if "county" in population.comparisons else ()),
            *((STATE,) if "state" in population.comparisons else ()),
        )
        populations.append(
            {
                "id": population.id,
                "label": population.label,
                "unit": population.unit,
                "universe": population.universe,
                "definition": population.definition,
                "exclusions": population.exclusions,
                "numerator": population.numerator,
                "denominator": population.denominator,
                "rows": [
                    {
                        "geography": c.geography,
                        "name": geography_name(c.geography),
                        "count": _reading(c.count, _count, _count),
                        "share": _reading(c.share, _percent, _points),
                        "inputs": c.share.inputs,
                    }
                    for c in compare(population, shown, facts)
                ],
            }
        )
    return {
        "populations": populations,
        "source": registry.source,
        "vintage": registry.vintage,
        "words": WORDS,
    }
