"""#363: deterministic scoring, claim ceilings and source-traceable reasons."""

from decimal import Decimal
from typing import Literal, cast

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


EVIDENCE = ComparabilityEvidence(
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
            "comparability_evidence": EVIDENCE,
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
        eligible=fact("eligible", 100, 2), received=fact("received", 20, 2), evidence=EVIDENCE
    )


@pytest.mark.parametrize(
    ("score", "band"),
    [(0.7, "strong"), (0.699999, "possible"), (0.4, "possible"), (0.399999, "weak"), (0, "weak")],
)
def test_thresholds(score: float, band: str) -> None:
    assert band_for(score) == band


def test_weights_missing_and_stable_ties() -> None:
    results = [
        score_match(MAPPING, POP, figure(), figure(40, geo="state:15")),
        score_match(MAPPING, POP, figure()),
        score_match(MAPPING, POP, figure(), strength="indirect"),
        score_match(MAPPING, POP, figure(None)),
    ]
    assert [(r.score, r.band) for r in results] == [
        (1, "strong"),
        (0.6, "possible"),
        (0.24, "weak"),
        (0, "insufficient"),
    ]
    other = results[1].model_copy(update={"program_id": "aaa"})
    assert rank_matches([results[1], other]) == rank_matches([other, results[1]])
    assert rank_matches([results[1], other])[0] == other
    population_tie = other.model_copy(update={"population_id": "aaa"})
    assert rank_matches([other, population_tie])[0] == population_tie


def test_caution_and_moderate_penalties() -> None:
    result = score_match(MAPPING, POP, figure(moe=100), figure(10, geo="state:15"))
    assert result.score == pytest.approx(0.15)
    assert "use with caution" in result.reason
    assert "higher" not in result.reason and "significant" not in result.reason
    assert score_match(MAPPING, POP, figure(moe=30)).score == 0.45
    assert score_match(MAPPING, POP, figure(moe=None)).band == "weak"


def test_corrected_significance_boundary() -> None:
    a = figure().model_copy(update={"value": 60, "moe": 3})
    b = figure(geo="state:15").model_copy(update={"value": 55, "moe": 4})
    assert score_match(MAPPING, POP, a, b).score == 0.6
    assert score_match(MAPPING, POP, a.model_copy(update={"value": 60.01}), b).score == 1


@pytest.mark.parametrize("field", list(ComparabilityEvidence.model_fields))
def test_each_uptake_mismatch_is_an_outreach_signal(field: str) -> None:
    raw = EVIDENCE.model_dump(mode="json")
    raw[field] = "https://example.org/other" if field == "participation_source" else "different"
    invalid = uptake().model_copy(update={"evidence": ComparabilityEvidence.model_validate(raw)})
    result = score_match(modeled(), POP, figure(), uptake=invalid)
    assert result.claim == "relevant_need" and result.score == 0.6
    assert f"outreach signal: uptake {field} mismatch" in result.reason


def test_valid_uptake_and_mapping_ceiling() -> None:
    result = score_match(modeled(), POP, figure(), uptake=uptake())
    assert result.claim == "comparable_nonparticipation" and result.score == pytest.approx(1.08)
    assert score_match(modeled(), POP, figure()).claim == "modeled_eligibility"
    lower = modeled().model_copy(update={"claim": "modeled_eligibility"})
    assert score_match(lower, POP, figure(), uptake=uptake()).claim == "modeled_eligibility"
    result = score_match(MAPPING, POP, figure(), uptake=uptake())
    assert "outreach signal: uptake comparability evidence missing" in result.reason
    assert result.claim == "relevant_need" and result.score == 0.6


def test_reason_traces_every_input_and_retains_uncertainty() -> None:
    benchmark = figure(40, geo="state:15")
    result = score_match(modeled(), POP, figure(), benchmark, uptake=uptake())
    for f in (*figure().inputs, *benchmark.inputs, uptake().eligible, uptake().received):
        fields = ("variable", "source", "table_id", "vintage", "geography")
        fields += ("method", "value", "moe", "endpoint")
        for token in (str(getattr(f, field)) for field in fields):
            assert token in result.reason
    assert result.figures == (figure(), benchmark)
    assert "agency decides eligibility" in result.reason
    assert result == score_match(modeled(), POP, figure(), benchmark, uptake=uptake())


@pytest.mark.parametrize(
    ("target", "field", "value", "problem"),
    [
        ("district", "geography", "state:15", "geography mismatch"),
        ("assessment", "geography", "state:15", "geography mismatch"),
        ("assessment", "unit", "persons", "unit mismatch"),
        ("received", "vintage", "2019–2023", "period mismatch"),
        (
            "district",
            "inputs",
            (figure().inputs[0].model_copy(update={"vintage": "2019–2023"}),),
            "period mismatch",
        ),
        ("received", "value", None, "uncertain or missing figures"),
        ("received", "moe", None, "uncertain or missing figures"),
        ("received", "reliability", "caution", "uncertain or missing figures"),
        ("received", "reliability", "unavailable", "uncertain or missing figures"),
        ("received", "value", 101, "invalid receipt range"),
    ],
)
def test_isolated_uptake_rejections(target: str, field: str, value: object, problem: str) -> None:
    m, d, u = modeled(), figure(), uptake()
    if target == "district":
        d = d.model_copy(update={field: value})
    elif target == "assessment":
        e = EVIDENCE.model_copy(update={field: value})
        m = m.model_copy(update={"comparability_evidence": e})
        u = u.model_copy(update={"evidence": e})
    else:
        u = u.model_copy(update={"received": u.received.model_copy(update={field: value})})
    result = score_match(m, POP, d, uptake=u)
    assert f"outreach signal: uptake {problem}" in result.reason
    assert result.claim == "relevant_need" and result.score == 0.6


@pytest.mark.parametrize(
    "change",
    [
        {"value": None},
        {"missing": (POP.numerator[0],)},
        {"inputs": ()},
        {"inputs": tuple(f.model_copy(update={"vintage": "2019–2023"}) for f in figure().inputs)},
    ],
)
def test_isolated_benchmark_rejections(change: dict[str, object]) -> None:
    b = figure(10, geo="state:15")
    assert score_match(MAPPING, POP, figure(), b).score == 1
    result = score_match(MAPPING, POP, figure(), b.model_copy(update=change))
    assert result.score == 0.6 and "No comparable prominence evidence" in result.reason


@pytest.mark.parametrize("change", [{"missing": (POP.numerator[0],)}, {"inputs": ()}])
def test_incomplete_district_is_insufficient(change: dict[str, object]) -> None:
    result = score_match(MAPPING, POP, figure().model_copy(update=change))
    assert result.band == "insufficient" and result.score == 0


@pytest.mark.parametrize("field", ["kind", "numerator", "denominator", "universe"])
def test_incompatible_population_is_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="population share mismatch"):
        score_match(MAPPING, POP, figure().model_copy(update={field: "incompatible"}))


def test_unknown_strength_and_mapping_rejected() -> None:
    with pytest.raises(ValueError, match="strength must be direct or indirect"):
        score_match(MAPPING, POP, figure(), strength=cast(Literal["direct", "indirect"], "unknown"))
    with pytest.raises(ValueError, match="mapping population mismatch"):
        score_match(MAPPING.model_copy(update={"population_id": "other"}), POP, figure())
    assert (
        score_match(MAPPING.model_copy(update={"review_status": "rejected"}), POP, figure()).band
        == "insufficient"
    )
