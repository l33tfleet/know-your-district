"""Offline candidate review gate; synthetic expectations are never expert judgments.

Run with pytest -s to print release evidence. Machine checks passing do not
promote preview: recorded economist/outreach judgments and Kevin's check are required.
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.analysis.populations import Derived
from app.populations import Population

RESEARCH_PROGRAMS = frozenset(
    {
        "preschool-open-doors",
        "child-care-subsidy",
        "public-pre-k",
        "head-start",
        "extra-help",
        "medicare-savings-programs",
        "med-quest",
        "wic",
        "eitc",
    }
)

FIXTURE = Path(__file__).parent / "fixtures/149_matching.json"


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["relevant", "irrelevant", "insufficient"]
    reviewer: str = Field(min_length=3)
    role: Literal["economist", "outreach"]
    reviewed_on: date
    evidence_reference: str = Field(min_length=10)
    origin: Literal["recorded human review"]


class SpotCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: Literal["Kevin"]
    checked_on: date
    evidence_reference: str = Field(min_length=10)
    accepted: Literal[True]
    origin: Literal["recorded human review"]


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    population: str
    program: str
    question: str
    program_scope: Literal["catalog", "research_only"]
    judgments: list[Judgment] | None
    kevin_check: SpotCheck | None


def expert_agreement(candidates: list[Candidate], predictions: dict[str, str]) -> bool:
    if len(candidates) < 20 or len({c.id for c in candidates}) != len(candidates):
        print("Expert agreement: not evaluated—review pending")
        return False
    for c in candidates:
        if (
            c.judgments is None
            or len(c.judgments) != 2
            or {j.role for j in c.judgments} != {"economist", "outreach"}
            or len({j.reviewer for j in c.judgments}) != 2
            or c.kevin_check is None
            or c.id not in predictions
        ):
            print("Expert agreement: not evaluated—review pending")
            return False
    votes = [(predictions[c.id], j.label) for c in candidates for j in c.judgments or ()]
    agreement = sum(a == b for a, b in votes) / len(votes)
    print(f"Expert agreement: {agreement:.0%}")
    return agreement >= 0.8


def candidates() -> list[Candidate]:
    from app.populations import load_populations
    from app.tools.matches import CATALOG
    from etl.programs import load_catalog
    from etl.programs.mappings import load_mappings

    rows = [
        Candidate.model_validate(c) for c in json.loads(FIXTURE.read_text())["review_candidates"]
    ]
    populations = {p.id for p in load_populations().populations}
    programs = {p.id for p in load_catalog(CATALOG)}
    mapped = {m.program_id for m in load_mappings()}
    for c in rows:
        if c.population not in populations:
            raise ValueError(f"Unknown candidate population: {c.population}")
        if c.program_scope == "catalog":
            if c.program not in programs:
                raise ValueError(f"Unknown catalog candidate program: {c.program}")
        elif c.program in programs | mapped:
            raise ValueError(f"Research candidate is already cataloged or mapped: {c.program}")
        elif c.program not in RESEARCH_PROGRAMS:
            raise ValueError(f"Unknown research candidate program: {c.program}")
    return rows


def test_review_pending_is_not_expert_agreement() -> None:
    rows = candidates()
    assert len(rows) == 20
    assert all(c.judgments is None and c.kevin_check is None for c in rows)
    assert not expert_agreement(rows, expectations())


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "synthetic"},
        {"reviewer": ""},
        {"evidence_reference": ""},
        {"reviewed_on": None},
        {"role": "model"},
    ],
)
def test_fabricated_or_incomplete_provenance_is_rejected(change: dict[str, object]) -> None:
    raw: dict[str, object] = dict(
        label="relevant",
        reviewer="Fixture reviewer",
        role="economist",
        reviewed_on="2026-11-07",
        evidence_reference="fixture://review-record",
        origin="recorded human review",
    )
    raw.update(change)
    with pytest.raises(ValidationError):
        Judgment.model_validate(raw)


def test_synthetic_policy_cases() -> None:
    from app.tools.matches import DistrictMatches
    from etl.boundaries import DistrictId
    from etl.programs.mappings import load_mappings

    district = DistrictId(chamber="house", district=22)
    mappings = load_mappings()
    expected = expectations()
    for c in candidates():
        if c.program_scope == "research_only":
            # Absence is checked separately; it is not evidence about scorer behavior.
            continue
        # Rejection is a synthetic scenario, not a human judgment of a real pair.
        rejected = expected[c.id] == "irrelevant"
        scenario = (
            tuple(m.model_copy(update={"review_status": "rejected"}) for m in mappings)
            if rejected
            else mappings
        )
        results = DistrictMatches(district).get_matches(scenario)
        found = any(m.population.id == c.population and m.program.id == c.program for m in results)
        observed = "relevant" if found else "irrelevant" if rejected else "insufficient"
        assert observed == expected[c.id], c.question


def expectations() -> dict[str, str]:
    return json.loads(FIXTURE.read_text())["synthetic_expectations"]


def reviewed_test_doubles() -> list[Candidate]:
    """Gate mechanics only: these fabricated test doubles never enter the fixture."""
    rows = candidates()
    reviewers: tuple[tuple[str, Literal["economist", "outreach"]], ...] = (
        ("Test economist", "economist"),
        ("Test outreach", "outreach"),
    )
    for c in rows:
        c.judgments = [
            Judgment(
                label="relevant",
                reviewer=name,
                role=role,
                reviewed_on=date(2026, 11, 7),
                evidence_reference="fixture://synthetic-gate-test",
                origin="recorded human review",
            )
            for name, role in reviewers
        ]
        c.kevin_check = SpotCheck(
            reviewer="Kevin",
            checked_on=date(2026, 11, 7),
            evidence_reference="fixture://synthetic-spot-check",
            accepted=True,
            origin="recorded human review",
        )
    return rows


@pytest.mark.parametrize("correct,passes", [(15, False), (16, True)])
def test_gate_requires_eighty_percent(correct: int, passes: bool) -> None:
    rows = reviewed_test_doubles()
    predictions = {c.id: "relevant" if i < correct else "irrelevant" for i, c in enumerate(rows)}
    assert expert_agreement(rows, predictions) is passes


@pytest.mark.parametrize(
    "missing", ["panel", "role", "reviewer", "kevin", "prediction", "size", "duplicate"]
)
def test_isolated_missing_review_evidence(missing: str) -> None:
    rows = reviewed_test_doubles()
    predictions = {c.id: "relevant" for c in rows}
    assert expert_agreement(rows, predictions)
    if missing == "panel":
        rows[0].judgments = None
    elif missing == "role":
        assert rows[0].judgments is not None
        rows[0].judgments[1].role = "economist"
    elif missing == "reviewer":
        assert rows[0].judgments is not None
        rows[0].judgments[1].reviewer = rows[0].judgments[0].reviewer
    elif missing == "kevin":
        rows[0].kevin_check = None
    elif missing == "prediction":
        del predictions[rows[0].id]
    elif missing == "size":
        rows.pop()
    else:
        rows[0].id = rows[1].id
    assert not expert_agreement(rows, predictions)


def test_candidates_resolve_or_explicitly_declare_research_scope() -> None:
    from app.populations import load_populations
    from app.tools.matches import CATALOG
    from etl.programs import load_catalog
    from etl.programs.mappings import load_mappings

    populations = {p.id for p in load_populations().populations}
    programs = {p.id for p in load_catalog(CATALOG)}
    mapped = {m.program_id for m in load_mappings()}
    raw = json.loads(FIXTURE.read_text())["review_candidates"]
    for c in raw:
        assert c["population"] in populations, c["id"]
        assert c["program_scope"] in ("catalog", "research_only"), c["id"]
        if c["program_scope"] == "catalog":
            assert c["program"] in programs, c["id"]
        else:
            assert c["program"] in RESEARCH_PROGRAMS, c["id"]
            assert c["program"] not in programs | mapped, c["id"]


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("population", "fixed_income", "Unknown candidate population: fixed_income"),
        ("program", "snpa", "Unknown catalog candidate program: snpa"),
        ("program", "preschool-open-door", "Unknown research candidate program"),
        ("program", "snap", "Research candidate is already cataloged or mapped"),
    ],
)
def test_candidate_reference_errors(
    field: str, value: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.loads(FIXTURE.read_text())
    row = raw["review_candidates"][6 if "Research" in error or "research" in error else 0]
    row[field] = value
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(sys.modules[__name__], "FIXTURE", path)
    with pytest.raises(ValueError, match=error):
        candidates()


def synthetic_share(population_id: str) -> tuple[Population, Derived]:
    """Published-cell shaped test doubles; never catalog facts or human judgments."""
    from app.analysis.populations import compare
    from app.models import Fact
    from app.populations import load_populations

    population = next(p for p in load_populations().populations if p.id == population_id)
    geography = "house:15:022:2022"
    facts = {
        (cell, geography): Fact(
            variable=cell,
            geography=geography,
            vintage="2020–2024",
            value=10 if cell in population.numerator else 100,
            moe=1,
            cv=0.06,
            reliability="reliable",
            source="Synthetic ACS fixture",
            table_id=cell.split("_")[0],
            method="published estimate and 90% margin of error",
            endpoint="https://example.org/synthetic",
            label="Synthetic cell",
        )
        for cell in population.numerator + population.denominator
    }
    return population, compare(population, (geography,), facts)[0].share


@pytest.mark.parametrize(
    "population_id,programs",
    [
        (
            "children_under_5",
            (
                ("preschool-open-doors", "POD subsidy", "Exact age cohort and approved provider"),
                (
                    "child-care-subsidy",
                    "General child-care subsidy",
                    "Care hours and work schedule",
                ),
                ("public-pre-k", "Public pre-K classroom", "School admission and capacity"),
                ("head-start", "Head Start services", "Service area and enrollment capacity"),
            ),
        ),
        (
            "older_below_poverty",
            (
                ("extra-help", "Part D drug-cost assistance", "Part D enrollment and resources"),
                (
                    "medicare-savings-programs",
                    "Medicare premium assistance",
                    "MSP category and resources",
                ),
            ),
        ),
    ],
)
def test_distinct_programs_keep_their_own_claims_and_reasons(
    population_id: str, programs: tuple[tuple[str, str, str], ...]
) -> None:
    from app.analysis.matching import MatchResult, rank_matches, score_match
    from etl.programs.mappings import ProgramMapping

    population, district = synthetic_share(population_id)
    results: list[MatchResult] = []
    # Reversed input makes collapsing or skipping records visible; these are
    # synthetic mappings, not permission to add absent programs to the catalog.
    for program, relevance, unknown in reversed(programs):
        mapping = ProgramMapping(
            population_id=population.id,
            program_id=program,
            relevance=relevance,
            observed_conditions=(population.definition,),
            unobserved_conditions=(unknown,),
            claim="relevant_need",
            review_status="pending",
        )
        results.append(score_match(mapping, population, district))
    ranked = rank_matches(results)
    assert len(ranked) == len(programs)
    assert [r.program_id for r in ranked] == sorted(p[0] for p in programs)
    by_program = {r.program_id: r for r in ranked}
    for program, relevance, unknown in programs:
        result = by_program[program]
        assert result.population_id == population_id
        assert result.band == "possible"
        assert result.claim == "relevant_need"
        assert result.uptake is None
        assert relevance in result.reason
        assert unknown in result.reason
        assert "Review: pending" in result.reason
        for other, other_relevance, other_unknown in programs:
            if other != program:
                assert other_relevance not in result.reason
                assert other_unknown not in result.reason


def test_fixed_income_never_merges_income_source_populations() -> None:
    from app.analysis.matching import MatchResult, rank_matches, score_match
    from app.populations import load_populations
    from etl.programs.mappings import load_mappings

    populations = {p.id: p for p in load_populations().populations}
    assert "fixed_income" not in populations
    social = populations["social_security"]
    retirement = populations["retirement"]
    combined = social.model_dump()
    combined["numerator"] = social.numerator + retirement.numerator
    with pytest.raises(ValidationError, match="B19055 and B19059 overlap and are never combined"):
        Population.model_validate(combined)
    results: list[MatchResult] = []
    for population_id in ("social_security", "retirement"):
        population, district = synthetic_share(population_id)
        mapping = load_mappings()[0].model_copy(
            update={
                "population_id": population_id,
                "relevance": population.definition,
            }
        )
        result = score_match(mapping, population, district)
        assert result.figures[0].numerator == population.numerator
        assert result.figures[0].value == pytest.approx(10)
        assert population.definition in result.reason
        assert result.claim == "relevant_need"
        results.append(result)
    assert {r.population_id for r in rank_matches(results)} == {"social_security", "retirement"}


def test_no_invented_med_quest_mapping_or_uptake() -> None:
    from app.tools.matches import DistrictMatches
    from etl.boundaries import DistrictId
    from etl.programs.mappings import load_mappings

    assert all(m.program_id != "med-quest" for m in load_mappings())
    results = DistrictMatches(DistrictId(chamber="house", district=22)).get_matches()
    assert results
    assert all(m.program.id != "med-quest" for m in results)
    assert all(m.result.uptake is None and m.result.claim == "relevant_need" for m in results)
