"""WO114: shared no-CV precedence for classification and Fact validation."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.analysis.reliability import Reliability, classify, flag_without_cv
from app.models import Fact


@pytest.mark.parametrize(
    "value,moe,expected",
    [
        (None, "10", "unavailable"),
        (None, "0", "unavailable"),
        (None, None, "unavailable"),
        ("0", "10", "caution"),
        ("0", "0", "caution"),
        ("0", None, "caution"),
        ("100", None, "caution"),
        ("100", "10", None),
        ("100", "0", None),
    ],
)
def test_flag_without_cv_precedence(
    value: str | None, moe: str | None, expected: Reliability | None
) -> None:
    assert (
        flag_without_cv(
            Decimal(value) if value is not None else None,
            Decimal(moe) if moe is not None else None,
        )
        == expected
    )


def fact_row(value: float | None, moe: float | None) -> dict[str, object]:
    # Synthetic validation fixture, never a published observation.
    return dict(
        variable="B01003_001E",
        geography="state:15",
        vintage="2020–2024",
        value=value,
        moe=moe,
        source="U.S. Census Bureau ACS 5-year",
        table_id="B01003",
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label="Estimate!!Total",
    )


@pytest.mark.parametrize(
    "value,moe,expected",
    [
        (None, 10.0, "unavailable"),
        (None, 0.0, "unavailable"),
        (None, None, "unavailable"),
        (0.0, 10.0, "caution"),
        (0.0, 0.0, "caution"),
        (0.0, None, "caution"),
        (100.0, None, "caution"),
    ],
)
def test_classify_and_fact_agree_without_cv(
    value: float | None, moe: float | None, expected: Reliability
) -> None:
    cv, flag = classify(
        Decimal(repr(value)) if value is not None else None,
        Decimal(repr(moe)) if moe is not None else None,
    )
    assert (cv, flag) == (None, expected)
    row = fact_row(value, moe) | dict(cv=None, reliability=flag)
    fact = Fact.model_validate(row)
    assert (fact.cv, fact.reliability) == (None, expected)
    assert Fact.model_validate_json(fact.model_dump_json()) == fact

    with pytest.raises(
        ValidationError, match="Unavailable, zero or missing-MOE estimates have no CV"
    ):
        Fact.model_validate(row | dict(cv=0.1))
    with pytest.raises(ValidationError, match="Reliability disagrees with estimate and CV"):
        Fact.model_validate(row | dict(reliability="reliable"))
    # CV rejection must take precedence even when the supplied flag is also wrong.
    with pytest.raises(
        ValidationError, match="Unavailable, zero or missing-MOE estimates have no CV"
    ):
        Fact.model_validate(row | dict(cv=0.1, reliability="reliable"))


def test_sampled_estimate_requires_cv_before_checking_flag() -> None:
    row = fact_row(100.0, 10.0) | dict(cv=None, reliability="reliable")
    with pytest.raises(ValidationError, match="Positive sampled estimates require a CV"):
        Fact.model_validate(row)
    with pytest.raises(ValidationError, match="Positive sampled estimates require a CV"):
        Fact.model_validate(row | dict(reliability="unavailable"))
