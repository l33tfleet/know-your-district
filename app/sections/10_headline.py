# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Headline: the district's name and the vintage line."""

from app.copy import geography_name, section_copy
from app.facts import acs_config
from app.page_state import PageState


def context(state: PageState) -> dict[str, object]:
    vintage, plan = acs_config()
    line: str = section_copy("headline")["vintage_line"]
    return {
        "heading": geography_name(state.district.fact_key),
        "vintage_line": line.format(vintage=vintage, plan=plan),
    }
