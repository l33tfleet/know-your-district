"""#30's reviewed comparison of two published estimates, as a worded group, never a number.

Mirrors `app/analysis/outreach.py` `_group`; that copy may delegate here later.
"""

from decimal import Decimal
from typing import Literal

from app.analysis.reliability import Z90
from app.models import Fact

Group = Literal["higher", "lower", "indeterminate", "caution", "missing"]


def compare(a: Fact | None, b: Fact | None) -> Group:
    """Whether `a` is clearly higher or lower than `b` at 90% confidence.

    Missing estimates and a vintage mismatch are `missing`; a caution flag on
    either side is `caution`; both short-circuit before any arithmetic.
    """
    if a is None or b is None or a.value is None or b.value is None or a.vintage != b.vintage:
        return "missing"
    if a.reliability == "caution" or b.reliability == "caution":
        return "caution"
    assert a.moe is not None and b.moe is not None
    # #30's reviewed rule: |a-b| / sqrt(MOEa² + MOEb²) > 1.645.
    # Squared Decimal arithmetic preserves the strict boundary and zero-MOE case.
    difference = Decimal(str(a.value)) - Decimal(str(b.value))
    variance = Decimal(str(a.moe)) ** 2 + Decimal(str(b.moe)) ** 2
    if difference**2 <= Z90**2 * variance:
        return "indeterminate"
    return "higher" if difference > 0 else "lower"
