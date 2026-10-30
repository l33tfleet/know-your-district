"""Human-authored outreach cases (`data/cases.yaml`); validated, no observations.

A case joins a population to a program with what the evidence supports and what it does not
(`docs/agent-docs/benefit-outreach.md`, `docs/agent-docs/district-data-build-guide.md`).
Startup calls `load_cases`, so a malformed record stops the server before it serves.
"""

from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Literal, Self, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.populations import load_populations
from app.sources import Identifier, Text

CASES_PATH = Path(__file__).resolve().parents[1] / "data/cases.yaml"

Gap = Literal[
    "unused_appropriation",
    "eligible_nonparticipation",
    "application_or_renewal_barrier",
    "underpayment",
    "redemption_or_expiration_loss",
    "service_capacity_or_fit",
]
ActionKind = Literal[
    "targeted_information", "navigator_referral", "outreach_planning_lead", "agency_follow_up"
]
Problem = Literal["geography", "population", "program"]
PROBLEMS: tuple[Problem, ...] = get_args(Problem)


class Program(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Text
    agency: Text
    url: HttpUrl
    rule_checked: date


class Failure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    gap: Gap
    note: Text


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: Text
    url: HttpUrl


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ActionKind
    links: Annotated[tuple[Link, ...], Field(min_length=1)]


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    population: Identifier
    program: Program
    failure: Failure
    claim: Text
    known: dict[Problem, Text]
    unknown: Annotated[dict[Problem, Text], Field(min_length=1)]
    action: Action
    research: Text

    @model_validator(mode="after")
    def every_problem_answered_once(self) -> Self:
        if both := [p for p in PROBLEMS if p in self.known and p in self.unknown]:
            raise ValueError(f"{self.id}: both known and unknown: {', '.join(both)}")
        if neither := [p for p in PROBLEMS if p not in self.known and p not in self.unknown]:
            raise ValueError(f"{self.id}: neither known nor unknown: {', '.join(neither)}")
        return self


class CaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cases: Annotated[tuple[Case, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        seen: set[str] = set()
        for record in self.cases:
            if record.id in seen:
                raise ValueError(f"duplicate case id: {record.id}")
            seen.add(record.id)
        return self


def load_cases(path: Path | None = None) -> CaseFile:
    """Read and validate the records against the population registry."""
    content = (path or CASES_PATH).read_text(encoding="utf-8")
    loaded = CaseFile.model_validate(yaml.safe_load(content))
    valid = {population.id for population in load_populations().populations}
    for record in loaded.cases:
        if record.population not in valid:
            raise ValueError(
                f"{record.id}: unknown population {record.population}; "
                f"valid ids: {', '.join(sorted(valid))}"
            )
    return loaded


@cache
def _by_id() -> dict[str, Case]:
    return {record.id: record for record in load_cases().cases}


def case(case_id: str) -> Case:
    return _by_id()[case_id]
