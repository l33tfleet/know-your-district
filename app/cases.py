"""Outreach cases (`data/cases.yaml`): a population, a program and the next step, as a record.

Fields follow `docs/agent-docs/benefit-outreach.md` (workflow) and the district-data
build guide (findings 4–5). Every case names what is known and unknown for the three
evidence problems; gap types and actions are the research's closed lists. The shipped
file is validated on import, so a bad record fails on the first brief, not mid-sentence.
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

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
Action = Literal[
    "targeted_information",
    "navigator_referral",
    "outreach_planning_lead",
    "agency_follow_up",
]
Problem = Literal["geography", "population", "program"]
PROBLEMS: tuple[Problem, ...] = ("geography", "population", "program")
Research = Annotated[Text, Field(pattern=r"^docs/research/benefit-program-access\.md#[a-z0-9-]+$")]


class Program(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Text
    agency: Text
    official_url: HttpUrl
    rule_checked_on: date


class Failure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Gap
    note: Text


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: Text
    url: HttpUrl


class NextAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Action
    note: Text
    steps: Annotated[tuple[Step, ...], Field(min_length=1)]


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    population: Identifier
    program: Program
    failure: Failure
    claim: Text
    known: dict[Problem, Text]
    unknown: dict[Problem, Text]
    action: NextAction
    research: Research

    @model_validator(mode="after")
    def every_problem_once(self) -> Self:
        both = set(self.known) & set(self.unknown)
        if both:
            raise ValueError(f"{self.id}: both known and unknown: {', '.join(sorted(both))}")
        missing = [p for p in PROBLEMS if p not in self.known and p not in self.unknown]
        if missing:
            raise ValueError(f"{self.id}: say what is known or unknown for {', '.join(missing)}")
        return self


class CaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: Annotated[tuple[Case, ...], Field(min_length=1)]


def load_cases(path: Path = CASES_PATH) -> tuple[Case, ...]:
    """Read and validate the cases; each population must exist in the registry."""
    loaded = CaseFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).cases
    known = {population.id for population in load_populations().populations}
    seen: set[str] = set()
    for case in loaded:
        if case.population not in known:
            raise ValueError(f"{case.id}: unknown population id {case.population!r}")
        if case.id in seen:
            raise ValueError(f"duplicate case id: {case.id}")
        seen.add(case.id)
    return loaded


CASES = load_cases()


def case(case_id: str) -> Case:
    return next(c for c in CASES if c.id == case_id)
