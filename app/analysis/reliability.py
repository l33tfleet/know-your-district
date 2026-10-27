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


def classify(value: Decimal | None, moe: Decimal | None) -> tuple[Decimal | None, Reliability]:
    """Classify normalized, nonnegative estimates; missing estimates take precedence.

    Zero estimates and missing MOEs have no CV. A positive estimate with zero
    MOE has CV zero. Decimal division preserves exact published boundaries.
    """
    if value is None:
        return None, "unavailable"
    if value == 0 or moe is None:
        return None, "caution"
    cv = moe / Z90 / value
    if cv <= RELIABLE_MAX:
        return cv, "reliable"
    if cv <= MODERATE_MAX:
        return cv, "moderate"
    return cv, "caution"
