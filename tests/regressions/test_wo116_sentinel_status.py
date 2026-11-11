"""WO116: numeric sentinel identity determines the cited missing-value status."""

from decimal import Decimal

import pytest

from app.models import Fact
from etl.census import CensusBatch, CensusError
from etl.facts import (
    _number,  # pyright: ignore[reportPrivateUsage]  # WO116 pins this helper's return contract.
    facts_from_batch,
)
from etl.indicators import INDICATORS


def _fact(estimate: str | None, moe: str | None) -> Fact:
    group = INDICATORS["median_gross_rent"]
    batch = CensusBatch(
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        vintage="2020–2024",
        labels={"B25064_001E": "Estimate!!Median gross rent"},
        rows=[
            {
                "state": "15",
                "B25064_001E": estimate,
                "B25064_001M": moe,
                "B25064_001EA": "estimate note",
                "B25064_001MA": "MOE note",
            }
        ],
    )
    return facts_from_batch(group, batch, "state:15")[0]


@pytest.mark.parametrize(
    "raw,value,status",
    [
        (None, None, "not available"),
        ("0", Decimal("0"), None),
        ("12.5", Decimal("12.5"), None),
        ("-555555555.0", None, "controlled"),
        (
            "-333333333.0",
            None,
            "not available: median in open-ended interval (top/bottom-coded)",
        ),
    ],
)
def test_number_returns_value_and_status(
    raw: str | None, value: Decimal | None, status: str | None
) -> None:
    assert _number(raw) == (value, status)


@pytest.mark.parametrize("raw", ["invalid", "NaN", "Infinity", "-Infinity", "-1"])
@pytest.mark.parametrize("position", ["estimate", "MOE"])
def test_invalid_numbers_are_still_rejected(raw: str, position: str) -> None:
    with pytest.raises(CensusError, match=r"^Invalid numeric Census cell$"):
        _fact(raw, "10") if position == "estimate" else _fact("100", raw)
