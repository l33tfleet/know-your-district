"""#363: deterministic match policy and the participation comparability gate."""

from decimal import Decimal

import pytest
from pydantic import HttpUrl

from app.analysis.matching import Uptake, band_for, rank_matches, score_match
from app.analysis.populations import Derived, compare
from app.analysis.reliability import classify
from app.models import Fact
from app.populations import load_populations
from etl.programs.mappings import ComparabilityEvidence, ProgramMapping, load_mappings

POP = next(p for p in load_populations().populations if p.id == "below_poverty_no_snap")
MAPPING = load_mappings()[0]
GEO = "house:15:022:2022"


def fact(cell: str, value: float | None, moe: float | None, geo: str = GEO) -> Fact:
    cv, flag = classify(
        None if value is None else Decimal(str(value)), None if moe is None else Decimal(str(moe))
    )
    return Fact(
        variable=cell,
        geography=geo,
        vintage="2020–2024",
        value=value,
        moe=moe,
        cv=None if cv is None else float(cv),
        reliability=flag,
        source="Census ACS",
        table_id=cell.split("_")[0],
        method="published",
        endpoint="https://example.org",
        label="Synthetic household estimate",
    )


def figure(value: float | None = 60, moe: float | None = 2, geo: str = GEO) -> Derived:
    cells = (fact("B22003_006E", value, moe, geo), fact("B22003_003E", 40, 2, geo))
    return compare(POP, [geo], {(f.variable, geo): f for f in cells})[0].share


def evidence() -> ComparabilityEvidence:
    return ComparabilityEvidence(
        participation_source=HttpUrl("https://example.org/receipt"),
        geography=GEO,
        period="2020–2024",
        unit="households",
        eligibility_definition="modeled rules",
        assistance_unit_definition="food purchasing unit",
        enrollment_receipt_definition="receipt",
        overlap="recipients are a subset of modeled eligible households",
        coverage="complete",
    )


def modeled() -> ProgramMapping:
    return ProgramMapping.model_validate(
        {
            **MAPPING.model_dump(),
            "claim": "comparable_nonparticipation",
            "comparability_evidence": evidence(),
            "modeling_evidence": {
                "method": "aggregate model",
                "rule_source": "https://example.org",
                "assumptions": ["synthetic"],
                "validation": "holdout",
                "evidence_url": "https://example.org",
            },
        }
    )


def uptake() -> Uptake:
    return Uptake(
        eligible=fact("eligible", 100, 2), received=fact("received", 20, 2), evidence=evidence()
    )


@pytest.mark.parametrize(
    ("score", "band"),
    [(0.7, "strong"), (0.699999, "possible"), (0.4, "possible"), (0.399999, "weak"), (0, "weak")],
)
def test_thresholds(score: float, band: str) -> None:
    assert band_for(score) == band


def test_weights_missing_and_stable_ties() -> None:
    strong = score_match(MAPPING, POP, figure(), figure(40, geo="state:15"))
    possible = score_match(MAPPING, POP, figure())
    weak = score_match(MAPPING, POP, figure(), strength="indirect")
    missing = score_match(MAPPING, POP, figure(None))
    assert (strong.score, possible.score, weak.score) == (1, 0.6, 0.24)
    assert (strong.band, possible.band, weak.band, missing.band) == (
        "strong",
        "possible",
        "weak",
        "insufficient",
    )
    other = possible.model_copy(update={"program_id": "aaa"})
    assert rank_matches([possible, other]) == rank_matches([other, possible])
    assert rank_matches([possible, other])[0].program_id == "aaa"


def test_caution_penalty_has_no_significance_claim() -> None:
    result = score_match(MAPPING, POP, figure(moe=100), figure(10, geo="state:15"))
    assert result.score == pytest.approx(0.15)
    assert "use with caution" in result.reason
    assert "higher" not in result.reason
    assert "significant" not in result.reason


def test_corrected_significance_boundary() -> None:
    # Equal squared difference and summed squared MOEs is indeterminate.
    a = figure().model_copy(update={"value": 60, "moe": 3})
    b = figure(geo="state:15").model_copy(update={"value": 55, "moe": 4})
    assert score_match(MAPPING, POP, a, b).score == 0.6
    a = a.model_copy(update={"value": 55.01})
    b = b.model_copy(update={"value": 50})
    assert score_match(MAPPING, POP, a, b).score == 1


@pytest.mark.parametrize(
    "field",
    [
        "geography",
        "period",
        "unit",
        "eligibility_definition",
        "assistance_unit_definition",
        "enrollment_receipt_definition",
        "overlap",
        "coverage",
        "participation_source",
    ],
)
def test_each_uptake_mismatch_is_an_outreach_signal(field: str) -> None:
    raw = evidence().model_dump(mode="json")
    raw[field] = "https://example.org/other" if field == "participation_source" else "different"
    invalid = uptake().model_copy(update={"evidence": ComparabilityEvidence.model_validate(raw)})
    result = score_match(modeled(), POP, figure(), uptake=invalid)
    assert result.claim == "relevant_need"
    assert f"outreach signal: uptake {field} mismatch" in result.reason
    assert result.score == 0.6


def test_valid_uptake_and_mapping_ceiling() -> None:
    result = score_match(modeled(), POP, figure(), uptake=uptake())
    assert result.claim == "comparable_nonparticipation"
    assert result.score == pytest.approx(1.08)
    assert score_match(MAPPING, POP, figure(), uptake=uptake()).claim == "relevant_need"
    assert score_match(modeled(), POP, figure()).claim == "modeled_eligibility"


def test_reason_traces_every_input_and_retains_uncertainty() -> None:
    result = score_match(modeled(), POP, figure(), uptake=uptake())
    for f in (*figure().inputs, uptake().eligible, uptake().received):
        for token in (
            f.variable,
            f.source,
            f.table_id,
            f.vintage,
            f.geography,
            f.method,
            str(f.value),
            str(f.moe),
            "reliable",
            f.endpoint,
        ):
            assert token in result.reason
    assert result.figures[0] == figure()
    assert "agency decides eligibility" in result.reason


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"geography": "state:15"}, "geography mismatch"),
        ({"vintage": "2019–2023"}, "period mismatch"),
        ({"value": None, "cv": None, "reliability": "unavailable"}, "uncertain or missing figures"),
        ({"moe": None, "cv": None, "reliability": "caution"}, "uncertain or missing figures"),
        ({"value": 101}, "invalid receipt range"),
    ],
)
def test_uptake_facts_must_support_assessment(change: dict[str, object], problem: str) -> None:
    u = uptake().model_copy(
        update={"received": Fact.model_validate({**uptake().received.model_dump(), **change})}
    )
    result = score_match(modeled(), POP, figure(), uptake=u)
    assert f"outreach signal: uptake {problem}" in result.reason
    assert result.claim == "relevant_need"


def test_moderate_missing_benchmark_and_rejected_evidence() -> None:
    assert score_match(MAPPING, POP, figure(moe=30)).score == 0.45
    assert score_match(MAPPING, POP, figure(), figure(None, geo="state:15")).score == 0.6
    rejected = MAPPING.model_copy(update={"review_status": "rejected"})
    assert score_match(rejected, POP, figure()).band == "insufficient"
    with pytest.raises(ValueError, match="mapping population mismatch"):
        score_match(MAPPING.model_copy(update={"population_id": "other"}), POP, figure())
    with pytest.raises(ValueError, match="population share mismatch"):
        score_match(MAPPING, POP, figure().model_copy(update={"kind": "sum"}))


def test_assessed_units_still_must_match_the_population() -> None:
    e = evidence().model_copy(update={"unit": "persons"})
    m = modeled().model_copy(update={"comparability_evidence": e})
    u = uptake().model_copy(update={"evidence": e})
    assert "uptake unit mismatch" in score_match(m, POP, figure(), uptake=u).reason
    assert score_match(MAPPING, POP, figure(moe=None)).band == "weak"
