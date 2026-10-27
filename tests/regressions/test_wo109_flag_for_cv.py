"""WO109: shared reliability classification preserves exact Decimal boundaries."""

from decimal import Decimal

import pytest

from app.analysis.reliability import Reliability, flag_for_cv


@pytest.mark.parametrize(
    "cv,expected",
    [
        ("0.15", "reliable"),
        ("0.15000000000000001", "moderate"),
        ("0.30", "moderate"),
        ("0.30000000000000001", "caution"),
    ],
)
def test_flag_for_cv_decimal_boundaries(cv: str, expected: Reliability) -> None:
    assert flag_for_cv(Decimal(cv)) == expected
