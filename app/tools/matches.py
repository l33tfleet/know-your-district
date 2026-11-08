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
from app.sources import Identifier
from etl.boundaries import DistrictId
from etl.programs import Program, load_catalog
from etl.programs.mappings import ProgramId, ProgramMapping, load_mappings

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


class MatchReference(BaseModel):
    """Selection identity only: card content can come only from the matching tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    district: DistrictId
    population_id: Identifier
    program_id: ProgramId


def find_matches(district: object, population: str | None = None) -> tuple[MatchReference, ...]:
    """Find ranked references in one validated district, optionally for a known population."""
    scope = DistrictId.model_validate(district)
    populations = {p.id for p in load_populations().populations}
    if population is not None and population not in populations:
        raise ValueError(f"Unknown population; valid: {', '.join(sorted(populations))}")
    return tuple(
        MatchReference(district=scope, population_id=m.population.id, program_id=m.program.id)
        for m in DistrictMatches(scope).get_matches()
        if population is None or m.population.id == population
    )


def resolve_matches(
    district: DistrictId, references: tuple[MatchReference, ...]
) -> tuple[ProgramMatch, ...]:
    """Resolve selections against current trusted matches; reject foreign/unknown identities."""
    for reference in references:
        if reference.district != district:
            raise ValueError("match reference outside page district")
    matches = {(m.population.id, m.program.id): m for m in DistrictMatches(district).get_matches()}
    resolved: list[ProgramMatch] = []
    for reference in references:
        key = reference.population_id, reference.program_id
        if key not in matches:
            raise ValueError("unknown match reference")
        resolved.append(matches[key])
    return tuple(resolved)
