"""Offline population-to-program contracts, without observations or eligibility counts.

The measure registry is the existing PopulationRegistry in app/populations.py:
each population ID resolves to its cells, universe, period and geography. Do not
create a parallel list of measures here. Evidence records document the basis for
a claim; schema validation is separate from program-expert review.
"""

from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from app.populations import REGISTRY_PATH, load_populations
from app.sources import Identifier, Text
from etl.programs import load_catalog

_DATA = Path(__file__).resolve().parents[2] / "data"
MAPPINGS_PATH = _DATA / "program_mappings.yaml"
ProgramId = Annotated[Text, StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]


class ModelingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    method: Text
    rule_source: HttpUrl
    assumptions: Annotated[tuple[Text, ...], Field(min_length=1)]
    validation: Text
    evidence_url: HttpUrl


class ComparabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    participation_source: HttpUrl
    geography: Text
    period: Text
    unit: Text
    overlap: Text
    coverage: Text


class ProgramMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    population_id: Identifier
    program_id: ProgramId
    relevance: Text
    # Explicit empty lists mean no observed or unobserved conditions, respectively.
    observed_conditions: tuple[Text, ...]
    unobserved_conditions: tuple[Text, ...]
    claim: Literal["relevant_need", "modeled_eligibility", "comparable_nonparticipation"]
    review_status: Literal["pending", "reviewed", "rejected"]
    modeling_evidence: ModelingEvidence | None = None
    comparability_evidence: ComparabilityEvidence | None = None

    @model_validator(mode="after")
    def supported_claim(self) -> Self:
        if self.claim != "relevant_need" and self.modeling_evidence is None:
            raise ValueError("modeling evidence is required for eligibility claims")
        if self.claim == "comparable_nonparticipation" and self.comparability_evidence is None:
            raise ValueError("comparability evidence is required for nonparticipation claims")
        return self


def load_mappings(
    path: Path = MAPPINGS_PATH,
    *,
    populations_path: Path = REGISTRY_PATH,
    programs_path: Path = _DATA / "programs.yaml",
) -> tuple[ProgramMapping, ...]:
    """Validate YAML, evidence and references to the canonical registries, offline.

    Pending expert review does not invalidate a relevance mapping. Neither a
    pending nor a reviewed status substitutes for evidence for stronger claims.
    Retired program identities remain resolvable through the catalog.
    """
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("Invalid mappings YAML") from exc
    mappings = TypeAdapter(
        Annotated[tuple[ProgramMapping, ...], Field(min_length=1)]
    ).validate_python(raw)
    population_ids = {p.id for p in load_populations(populations_path).populations}
    program_ids = {p.id for p in load_catalog(programs_path)}
    seen: set[tuple[str, str]] = set()
    for mapping in mappings:
        if mapping.population_id not in population_ids:
            raise ValueError(f"Unknown population ID: {mapping.population_id}")
        if mapping.program_id not in program_ids:
            raise ValueError(f"Unknown program ID: {mapping.program_id}")
        key = (mapping.population_id, mapping.program_id)
        if key in seen:
            raise ValueError(f"Duplicate mapping: {key}")
        seen.add(key)
    return mappings
