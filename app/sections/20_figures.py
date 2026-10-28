# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Three figures (population, share 65+, median household income) for the district, each with
its ±MOE, reliability in words and full citation, and the state's figure beside it."""

from collections.abc import Callable

from app.copy import Copy, geography_name, section_copy
from app.facts import FactStore, acs_config
from app.models import Fact
from app.page_state import PageState
from etl.indicators import INDICATORS

STATE = "state:15"
FORMATS: dict[str, Callable[[float], str]] = {
    "population": lambda v: f"{v:,.0f}",
    "age_65_share": lambda v: f"{v:.1f}%",
    "median_household_income": lambda v: f"${v:,.0f}",
}


def reading(
    geography: str, fact: Fact | None, fmt: Callable[[float], str], copy: Copy
) -> dict[str, object]:
    if fact is None:
        return {
            "geography": geography,
            "found": False,
            "word": copy["reliability"]["unavailable"],
            "reliability": "unavailable",
            "value_text": copy["no_row"],
        }
    return {
        "geography": geography,
        "found": True,
        "value": fact.value,
        "value_text": fmt(fact.value) if fact.value is not None else copy["not_available"],
        "moe": fact.moe,
        "moe_text": "±" + fmt(fact.moe) if fact.moe is not None else copy["no_moe"],
        "reliability": fact.reliability,
        "word": copy["reliability"][fact.reliability],
    }


def citation(fact: Fact, fmt: Callable[[float], str], copy: Copy) -> dict[str, object]:
    return {
        "fact": fact,
        "geography_name": geography_name(fact.geography),
        "moe_text": "±" + fmt(fact.moe) if fact.moe is not None else copy["no_moe"],
        "cv_text": f"{fact.cv * 100:.1f}%" if fact.cv is not None else copy["no_cv"],
    }


def context(state: PageState) -> dict[str, object]:
    copy = section_copy("figures")
    vintage, _ = acs_config()
    district = state.district.fact_key
    variables = {figure: INDICATORS[figure].variables[0] for figure in FORMATS}
    facts = FactStore.default().get(
        ((v, g) for v in variables.values() for g in (district, STATE)), vintage
    )
    figures: list[dict[str, object]] = []
    for figure, fmt in FORMATS.items():
        found = [facts.get((variables[figure], g)) for g in (district, STATE)]
        figures.append(
            {
                "key": figure,
                "variable": variables[figure],
                "name": copy["names"][figure],
                "district": reading(district, found[0], fmt, copy),
                "state": reading(STATE, found[1], fmt, copy),
                "citations": [citation(f, fmt, copy) for f in found if f is not None],
            }
        )
    return {"figures": figures}
