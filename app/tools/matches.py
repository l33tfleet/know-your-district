"""District-bound, read-only outreach matching; detached figures retain their sources.

No uptake data is supplied by the current mappings. A survey nonreceipt cell is
never passed as comparable uptake or as an eligibility model.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.analysis.matching import MatchResult, rank_matches, score_match
from app.analysis.populations import Derived, compare
from app.facts import FactStore
from app.populations import Population, load_populations
from etl.boundaries import DistrictId
from etl.programs import Program, load_catalog
from etl.programs.mappings import ProgramMapping, load_mappings

CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


class ProgramMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    population: Population
    program: Program
    mapping: ProgramMapping
    count: Derived
    result: MatchResult


class DistrictMatches:
    """Bind to a validated brief district; calls cannot substitute another geography."""

    def __init__(self, district: object) -> None:
        self._district = DistrictId.model_validate(district)

    def get_matches(
        self, mappings: tuple[ProgramMapping, ...] | None = None
    ) -> tuple[ProgramMatch, ...]:
        registry = load_populations()
        populations = {p.id: p for p in registry.populations}
        programs = {p.id: p for p in load_catalog(CATALOG)}
        selected = tuple(
            m
            for m in (load_mappings() if mappings is None else mappings)
            if m.review_status != "rejected" and programs[m.program_id].retired is None
        )
        store = FactStore.default()
        # FactStore's legacy empty-store fallback is inappropriate for this tool.
        if not store.path.is_file():
            raise FileNotFoundError(f"Matches fact store is missing: {store.path}")
        geography = self._district.fact_key
        cells = {
            c
            for m in selected
            for c in populations[m.population_id].numerator
            + populations[m.population_id].denominator
        }
        facts = store.get(
            ((c, g) for c in cells for g in (geography, "state:15")), registry.vintage
        )
        matches: dict[tuple[str, str], ProgramMatch] = {}
        for mapping in selected:
            population = populations[mapping.population_id]
            district, benchmark = compare(population, (geography, "state:15"), facts)
            result = score_match(mapping, population, district.share, benchmark.share)
            matches[result.population_id, result.program_id] = ProgramMatch(
                population=population,
                program=programs[mapping.program_id],
                mapping=mapping,
                count=district.count,
                result=result,
            )
        ranked = rank_matches([m.result for m in matches.values()])
        return tuple(matches[r.population_id, r.program_id] for r in ranked)
