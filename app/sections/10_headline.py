# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Headline: the district's name and the vintage line."""

from markupsafe import Markup

from app.boundary_store import load_boundaries
from app.copy import geography_name, section_copy
from app.facts import acs_config
from app.page_state import PageState
from app.svg import render_svg


def context(state: PageState) -> dict[str, object]:
    vintage, plan = acs_config()
    wording = section_copy("headline")
    line: str = wording["vintage_line"]
    heading = geography_name(state.district.fact_key)
    boundary = load_boundaries().district(state.district.fact_key)
    credits = list(
        dict.fromkeys(
            island.coastline.source.credit
            for island in boundary.islands
            if island.coastline.status == "available"
        )
    )
    return {
        "heading": heading,
        "boundary_label": wording["boundary_label"].format(
            heading=heading, islands="; ".join(i.name for i in boundary.islands)
        ),
        # Only the sole renderer produces trusted markup; source text stays escaped.
        "boundary_svg": Markup(
            render_svg(boundary.geometry, heading, [(i.name, i.geometry) for i in boundary.islands])
        ),
        "boundary_source": wording["boundary_source"].format(credit=boundary.attribution.credit),
        "coastline_source": wording["coastline_source"].format(credit="; ".join(credits))
        if credits
        else "",
        "vintage_line": line.format(vintage=vintage, plan=plan),
    }
