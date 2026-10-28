"""Pure ACS reliability classification from a published 90% margin of error."""

from decimal import Decimal
from typing import Literal

Z90 = Decimal("1.645")
RELIABLE_MAX = Decimal("0.15")
MODERATE_MAX = Decimal("0.30")

Reliability = Literal["reliable", "moderate", "caution", "unavailable"]

FLAG_WORDS: dict[Reliability, str] = {
    "reliable": "reliable",
    "moderate": "moderate: use with care",
    "caution": "use with caution",
    "unavailable": "not available",
}


def flag_for_cv(cv: Decimal) -> Reliability:
    """Classify a coefficient of variation using the shared Decimal thresholds."""
    if cv <= RELIABLE_MAX:
        return "reliable"
    if cv <= MODERATE_MAX:
        return "moderate"
    return "caution"


def flag_without_cv(value: Decimal | None, moe: Decimal | None) -> Reliability | None:
    """Resolve missing/zero precedence, or return None when a CV is needed."""
    if value is None:
        return "unavailable"
    if value == 0 or moe is None:
        return "caution"
    return None


def classify(value: Decimal | None, moe: Decimal | None) -> tuple[Decimal | None, Reliability]:
    """Classify normalized, nonnegative estimates; missing estimates take precedence.

    Zero estimates and missing MOEs have no CV. A positive estimate with zero
    MOE has CV zero. Decimal division preserves exact published boundaries.
    """
    flag = flag_without_cv(value, moe)
    if flag is not None:
        return None, flag
    assert value is not None
    assert moe is not None
    cv = moe / Z90 / value
    return cv, flag_for_cv(cv)
