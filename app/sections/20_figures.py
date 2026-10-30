# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Three figures (population, share 65+, median household income) for the district, each with
its ±MOE, reliability in words and full citation, and county and state figures beside it."""

from app.analysis.intervals import interval_layout
from app.brief_facts import FORMATS, STATE, BriefFacts, citation, reading
from app.copy import geography_name, section_copy
from app.counties import load_mapping
from app.features import enabled
from app.page_state import PageState
from app.source_links import MAPPING_URL, evidence_link, source_links


def context(state: PageState) -> dict[str, object]:
    copy = section_copy("figures")
    checks_enabled = enabled("source_links", state)
    selected = BriefFacts(state.district, load_mapping()[state.district.fact_key])
    district = selected.district
    shares = selected.shares
    counties = selected.counties
    geographies = selected.geographies
    variables = selected.variables
    facts = selected.facts
    figures: list[dict[str, object]] = []
    for figure, fmt in FORMATS.items():
        found = [facts.get((variables[figure], g)) for g in geographies]
        figures.append(
            {
                "key": figure,
                "variable": variables[figure],
                "name": copy["names"][figure],
                "district": reading(district, found[0], fmt, copy),
                "state": reading(STATE, found[-1], fmt, copy),
                "counties": [
                    reading(g, facts.get((variables[figure], g)), fmt, copy)
                    | {"label": geography_name(g)}
                    for g in counties
                ],
                "intervals": [
                    {
                        "mark": mark,
                        "label": geography_name(mark.geography),
                        "role": "district"
                        if mark.geography == district
                        else "state"
                        if mark.geography == STATE
                        else "county",
                    }
                    for mark in interval_layout(found)
                ],
                "citations": [
                    citation(f, fmt, copy) | {"links": source_links(f) if checks_enabled else ()}
                    for f in found
                    if f is not None
                ],
            }
        )
    return {
        "figures": figures,
        "multi_county": len(shares) > 1,
        "county_shares": [
            {"name": geography_name(s.county), "share_text": f"{s.area_share * 100:.1f}%"}
            for s in shares
        ],
        "mapping": shares[0],
        "mapping_links": [
            evidence_link(shares[0].district_source, "district_source"),
            evidence_link(shares[0].county_source, "county_source"),
            evidence_link(MAPPING_URL, "mapping_file"),
        ]
        if checks_enabled
        else [],
    }
