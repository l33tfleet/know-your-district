"""Offline candidate review gate; synthetic expectations are never expert judgments.

Run with pytest -s to print release evidence. Machine checks passing do not
promote preview: recorded economist/outreach judgments and Kevin's check are required.
"""

import json
from datetime import date
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    return [
        Candidate.model_validate(c) for c in json.loads(FIXTURE.read_text())["review_candidates"]
    ]


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
