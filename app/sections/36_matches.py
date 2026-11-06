# ruff: noqa: N999 -- sections use the NN_name.py discovery convention
"""Inspectable population/program connections, with the evidence ceiling visible.

Use the canonical population registry and mapping contracts. Missing facts remain
unavailable; neither review status nor a survey count establishes eligibility.
"""

from pathlib import Path

from app.analysis.populations import total
from app.analysis.reliability import FLAG_WORDS
from app.copy import geography_name
from app.facts import FactStore
from app.page_state import PageState
from app.populations import load_populations
from etl.programs import load_catalog
from etl.programs.mappings import load_mappings

# The expanded evidence belongs on screen to preserve the one-page print brief.
PRINT = False
CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"
CLAIMS = {
    "relevant_need": "Relevant need only — potential outreach audience",
    "modeled_eligibility": "Modeled eligibility — agency confirmation required",
    "comparable_nonparticipation": "Comparable nonparticipation — aggregate estimate",
}


def context(state: PageState) -> dict[str, object]:
    registry = load_populations()
    populations = {p.id: p for p in registry.populations}
    programs = {p.id: p for p in load_catalog(CATALOG)}
    mappings = tuple(
        m
        for m in load_mappings()
        if m.review_status != "rejected" and programs[m.program_id].retired is None
    )
    geography = state.district.fact_key
    cells = {c for m in mappings for c in populations[m.population_id].numerator}
    facts = FactStore.default().get(((c, geography) for c in cells), registry.vintage)
    matches: list[dict[str, object]] = []
    for mapping in mappings:
        population = populations[mapping.population_id]
        figure = total(population.numerator, geography, facts)
        matches.append(
            {
                "mapping": mapping,
                "population": population,
                "program": programs[mapping.program_id],
                "claim": CLAIMS[mapping.claim],
                "figure": figure,
                "value": "Not available" if figure.value is None else f"{figure.value:,.0f}",
                "moe": "no margin of error" if figure.moe is None else f"±{figure.moe:,.0f}",
                "reliability": FLAG_WORDS[figure.reliability],
            }
        )
    return {
        "matches": matches,
        "source": registry.source,
        "vintage": registry.vintage,
        "geography": geography,
        "geography_name": geography_name(geography),
    }
