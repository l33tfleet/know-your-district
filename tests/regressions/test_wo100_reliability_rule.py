"""WO100: one Decimal reliability rule and documented words for all consumers."""

from decimal import Decimal
from math import nextafter
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.reliability import (
    FLAG_WORDS,
    MODERATE_MAX,
    RELIABLE_MAX,
    Z90,
    Reliability,
    classify,
)
from app.models import Fact
from etl.census import CensusBatch
from etl.facts import facts_from_batch
from etl.indicators import INDICATORS


def test_decimal_constants_and_documented_words() -> None:
    assert Decimal("1.645") == Z90
    assert Decimal("0.15") == RELIABLE_MAX
    assert Decimal("0.30") == MODERATE_MAX
    assert all(isinstance(value, Decimal) for value in (Z90, RELIABLE_MAX, MODERATE_MAX))
    assert FLAG_WORDS == {
        "reliable": "reliable",
        "moderate": "moderate: use with care",
        "caution": "use with caution",
        "unavailable": "not available",
    }
    documentation = (Path(__file__).resolve().parents[2] / "docs/data.md").read_text()
    for words in FLAG_WORDS.values():
        assert words in documentation


@pytest.mark.parametrize(
    "value,moe,expected_cv,flag",
    [
        ("100", "24.675", "0.15", "reliable"),
        ("100", "24.675000000000001", "0.1500000000000000060790273556", "moderate"),
        ("100", "49.35", "0.30", "moderate"),
        ("100", "49.350000000000001", "0.3000000000000000060790273556", "caution"),
        ("0", "10", None, "caution"),
        ("0", "0", None, "caution"),
        ("100", None, None, "caution"),
        (None, "10", None, "unavailable"),
        (None, None, None, "unavailable"),
        ("100", "0", "0", "reliable"),
    ],
)
def test_classify_decimal_boundaries_and_missing_values(
    value: str | None, moe: str | None, expected_cv: str | None, flag: Reliability
) -> None:
    assert classify(
        Decimal(value) if value is not None else None,
        Decimal(moe) if moe is not None else None,
    ) == (Decimal(expected_cv) if expected_cv is not None else None, flag)


def fact_data() -> dict[str, object]:
    # Synthetic validation fixture, never a published observation.
    return dict(
        variable="B01003_001E",
        geography="state:15",
        vintage="2020–2024",
        value=100,
        moe=10,
        cv=0.1,
        reliability="reliable",
        source="U.S. Census Bureau ACS 5-year",
        table_id="B01003",
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label="Estimate!!Total",
    )


@pytest.mark.parametrize(
    "moe,flag",
    [
        ("24.675", "reliable"),
        ("24.676", "moderate"),
        ("49.35", "moderate"),
        ("49.351", "caution"),
        ("0", "reliable"),
        (None, "caution"),
    ],
)
def test_etl_and_validator_agree_with_classify(moe: str | None, flag: Reliability) -> None:
    raw = CensusBatch(
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        vintage="2020–2024",
        labels={"B01003_001E": "Estimate!!Total"},
        rows=[
            {
                "state": "15",
                "B01003_001E": "100",
                "B01003_001M": moe,
                "B01003_001EA": None,
                "B01003_001MA": None,
            }
        ],
    )
    cv, reliability = classify(Decimal("100"), Decimal(moe) if moe is not None else None)
    fact = facts_from_batch(INDICATORS["population"], raw, "state:15")[0]
    assert fact.reliability == reliability == flag
    assert fact.cv == (float(cv) if cv is not None else None)
    assert Fact.model_validate_json(fact.model_dump_json()) == fact


@pytest.mark.parametrize(
    "cv,flag",
    [
        (0.15, "reliable"),
        (nextafter(0.15, 1), "moderate"),
        (0.30, "moderate"),
        (nextafter(0.30, 1), "caution"),
    ],
)
def test_validator_keeps_supplied_float_cv(cv: float, flag: Reliability) -> None:
    # Validation classifies the supplied CV rather than recomputing it from MOE.
    row = fact_data() | dict(cv=cv, reliability=flag)
    assert Fact.model_validate(row).cv == cv
    wrong: Reliability = "caution" if flag != "caution" else "reliable"
    with pytest.raises(ValidationError, match="Reliability disagrees with estimate and CV"):
        Fact.model_validate(row | dict(reliability=wrong))


def test_validator_requires_cv_for_positive_sampled_estimate() -> None:
    with pytest.raises(ValidationError, match="Positive sampled estimates require a CV"):
        Fact.model_validate(fact_data() | dict(cv=None))


@pytest.mark.parametrize(
    "change",
    [
        dict(value=None, reliability="unavailable"),
        dict(value=0, reliability="caution"),
        dict(moe=None, reliability="caution"),
    ],
)
def test_validator_forbids_cv_when_undefined(change: dict[str, object]) -> None:
    with pytest.raises(
        ValidationError, match="Unavailable, zero or missing-MOE estimates have no CV"
    ):
        Fact.model_validate(fact_data() | change)
