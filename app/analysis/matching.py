"""Deterministic match policy; scores are ranking weights, never eligibility probabilities."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.analysis.populations import Derived
from app.analysis.reliability import FLAG_WORDS
from app.models import Fact
from app.populations import Population
from etl.programs.mappings import ComparabilityEvidence, ProgramMapping

Band = Literal["strong", "possible", "weak", "insufficient"]
STRENGTH = {"direct": 1.0, "indirect": 0.4}
RELIABILITY = {"reliable": 1.0, "moderate": 0.75, "caution": 0.25, "unavailable": 0.0}


class Uptake(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    eligible: Fact
    received: Fact
    evidence: ComparabilityEvidence


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    population_id: str
    program_id: str
    score: float
    band: Band
    claim: Literal["relevant_need", "modeled_eligibility", "comparable_nonparticipation"]
    reason: str
    figures: tuple[Derived, ...]
    uptake: Uptake | None


def band_for(score: float) -> Band:
    return "strong" if score >= 0.7 else "possible" if score >= 0.4 else "weak"


def rank_matches(matches: Sequence[MatchResult]) -> tuple[MatchResult, ...]:
    return tuple(sorted(matches, key=lambda m: (-m.score, m.program_id, m.population_id)))


def _citation(f: Fact) -> str:
    return (
        f"{f.variable}: {f.value}; MOE {f.moe}; {FLAG_WORDS[f.reliability]}; "
        f"{f.source}; {f.table_id}; {f.vintage}; {f.geography}; {f.method}; {f.endpoint}"
    )


def _describe(d: Derived) -> str:
    return (
        f"{d.kind}: {d.value}; MOE {d.moe}; {FLAG_WORDS[d.reliability]}; "
        f"{d.geography}; {d.universe}; {d.method}; inputs: "
        + " | ".join(_citation(f) for f in d.inputs)
    )


def _uptake_problem(mapping: ProgramMapping, p: Population, d: Derived, u: Uptake) -> str | None:
    expected = mapping.comparability_evidence
    if expected is None:
        return "comparability evidence missing"
    for field in ComparabilityEvidence.model_fields:
        if getattr(expected, field) != getattr(u.evidence, field):
            return f"{field} mismatch"
    if expected.unit != p.unit:
        return "unit mismatch"
    for f in (u.eligible, u.received):
        if f.geography != d.geography or f.geography != expected.geography:
            return "geography mismatch"
        if f.vintage != expected.period or any(f.vintage != x.vintage for x in d.inputs):
            return "period mismatch"
        if f.value is None or f.moe is None or f.reliability in ("caution", "unavailable"):
            return "uncertain or missing figures"
    assert u.eligible.value is not None and u.received.value is not None
    if u.received.value > u.eligible.value:
        return "invalid receipt range"
    return None


def _available(d: Derived) -> bool:
    return d.value is not None and bool(d.inputs) and not d.missing


def score_match(
    mapping: ProgramMapping,
    population: Population,
    district: Derived,
    benchmark: Derived | None = None,
    *,
    strength: Literal["direct", "indirect"] = "direct",
    uptake: Uptake | None = None,
) -> MatchResult:
    if mapping.population_id != population.id:
        raise ValueError("mapping population mismatch")
    if strength not in STRENGTH:
        raise ValueError("strength must be direct or indirect")
    figures = (district,) if benchmark is None else (district, benchmark)
    for d in figures:
        if (
            d.kind != "share"
            or d.numerator != population.numerator
            or d.denominator != population.denominator
            or d.universe != population.universe
        ):
            raise ValueError("population share mismatch")
    available = _available(district) and mapping.review_status != "rejected"
    prominence, reliability = 0.6, RELIABILITY[district.reliability]
    comparison = "No comparable prominence evidence."
    if benchmark is not None:
        comparable = (
            _available(benchmark) and len({f.vintage for d in figures for f in d.inputs}) == 1
        )
        if comparable:
            reliability = min(reliability, RELIABILITY[benchmark.reliability])
            if district.reliability == "caution" or benchmark.reliability == "caution":
                comparison = "Prominence uncertain; use with caution."
            elif (
                district.value is not None
                and district.moe is not None
                and benchmark.moe is not None
            ):
                difference = Decimal(str(district.value)) - Decimal(str(benchmark.value))
                variance = Decimal(str(district.moe)) ** 2 + Decimal(str(benchmark.moe)) ** 2
                if difference > 0 and difference**2 > variance:
                    prominence, comparison = 1.0, "Higher comparable population share."
                else:
                    comparison = "No evidence of a higher comparable population share."
    claim = "relevant_need" if mapping.claim == "relevant_need" else "modeled_eligibility"
    multiplier, uptake_note = 1.0, "Comparable uptake unavailable."
    if uptake is not None:
        problem = _uptake_problem(mapping, population, district, uptake)
        if problem is not None:
            claim, uptake_note = "relevant_need", f"outreach signal: uptake {problem}."
        else:
            assert uptake.eligible.value is not None and uptake.received.value is not None
            multiplier += (uptake.eligible.value - uptake.received.value) / uptake.eligible.value
            reliability = min(
                reliability,
                RELIABILITY[uptake.eligible.reliability],
                RELIABILITY[uptake.received.reliability],
            )
            claim, uptake_note = mapping.claim, "Validated comparable uptake."
    score = (
        round(STRENGTH[strength] * prominence * reliability * multiplier, 12) if available else 0
    )
    reason = (
        f"{comparison} {uptake_note} {mapping.relevance} "
        f"Review: {mapping.review_status}. Unknown conditions: "
        + "; ".join(mapping.unobserved_conditions)
        + ". Program may help; the agency decides eligibility. "
        + " || ".join(_describe(d) for d in figures)
    )
    if uptake is not None:
        reason += " || " + _citation(uptake.eligible) + " | " + _citation(uptake.received)
    return MatchResult(
        population_id=population.id,
        program_id=mapping.program_id,
        score=score,
        band=band_for(score) if available else "insufficient",
        claim=claim,
        reason=reason,
        figures=figures,
        uptake=uptake,
    )
