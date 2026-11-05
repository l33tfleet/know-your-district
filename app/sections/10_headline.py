# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""District title, State boundary drawing and provenance, separate from ACS."""

from app.boundary_store import load_boundaries
from app.copy import geography_name, section_copy
from app.facts import acs_config
from app.page_state import PageState
from app.svg import render_svg


def context(state: PageState) -> dict[str, object]:
    vintage, plan = acs_config()
    words = section_copy("headline")
    boundary = load_boundaries().district(state.district.fact_key)
    heading = geography_name(state.district.fact_key)
    return {
        "heading": heading,
        "vintage_line": words["vintage_line"].format(vintage=vintage, plan=plan),
        "outline": render_svg(
            boundary.geometry, heading, [(i.name, i.geometry) for i in boundary.islands]
        ),
        "outline_label": "; ".join([heading, *(i.name for i in boundary.islands)]),
        "islands": ", ".join(i.name for i in boundary.islands),
        "provenance": boundary.attribution.provenance,
        # The original layer credits remain verbatim in data/geo/*.credit.txt.
        # Product rule 6 governs visible names; disclose the spelling correction.
        "credit": boundary.attribution.credit.replace("Hawaii", "Hawaiʻi"),
        "coastline_sources": list(
            dict.fromkeys(
                (
                    i.coastline.source.credit.replace("Hawaii", "Hawaiʻi"),
                    i.coastline.source.service_url,
                    str(i.coastline.source.retrieved_on),
                )
                for i in boundary.islands
                if i.coastline.status == "available"
            )
        ),
    }
