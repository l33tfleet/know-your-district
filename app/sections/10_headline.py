# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Headline: the district's name and the vintage line."""

from app.boundary_store import load_boundaries
from app.copy import geography_name, section_copy
from app.facts import acs_config
from app.page_state import PageState
from app.svg import render_svg


def context(state: PageState) -> dict[str, object]:
    vintage, plan = acs_config()
    line: str = section_copy("headline")["vintage_line"]
    boundary = load_boundaries().district(state.district.fact_key)
    heading = geography_name(state.district.fact_key)
    source_line: str = section_copy("headline")["boundary_line"]
    outline_label: str = section_copy("headline")["outline_label"]
    source = boundary.attribution.provenance
    return {
        "heading": heading,
        "vintage_line": line.format(vintage=vintage, plan=plan),
        "outline": render_svg(
            boundary.geometry,
            heading,
            tuple((island.name, island.geometry) for island in boundary.islands),
        ),
        "outline_label": outline_label.format(
            district=heading, islands="; ".join(island.name for island in boundary.islands)
        ),
        "boundary_url": str(source.source_url),
        "boundary_line": source_line.format(
            vintage=source.vintage, method=source.method, retrieved_on=source.retrieved_on
        ),
    }
