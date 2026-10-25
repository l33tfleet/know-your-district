"""WO61: open-ended median MOEs remain unavailable without aborting a load."""

from pathlib import Path

import pytest

from app.models import Fact
from etl.census import CensusBatch, load_config
from etl.facts import facts_from_batch
from etl.indicators import INDICATORS


@pytest.mark.parametrize(
    "name,estimate,annotation",
    [
        ("median_gross_rent", "3501", "3,500+"),
        ("median_household_income", "250001", "250,000+"),
        ("median_household_income", "2499", "2,500-"),
    ],
)
def test_open_ended_median_preserves_estimate_annotations_and_provenance(
    name: str, estimate: str, annotation: str
) -> None:
    config = load_config(Path(__file__).resolve().parents[2] / "config.toml")
    group = INDICATORS[name]
    variable = group.variables[0]
    moe_variable = group.moe_variable(variable)
    raw = CensusBatch(
        config.base_url.format(year=config.year),
        config.vintage,
        {variable: config.labels[variable].format(year=config.year)},
        [
            {
                "state": "15",
                variable: estimate,
                variable + "A": annotation,
                moe_variable: "-333333333",
                moe_variable + "A": "***",
            }
        ],
    )

    fact = facts_from_batch(group, raw, "state:15")[0]

    assert fact.value == float(estimate)
    assert fact.moe is None and fact.cv is None
    assert fact.reliability == "caution"
    assert fact.estimate_annotation == annotation and fact.moe_annotation == "***"
    assert "MOE not available: median in open-ended interval (top/bottom-coded)" in fact.method
    assert f"estimate annotation: {annotation}" in fact.method
    assert "MOE annotation: ***" in fact.method
    assert fact.variable == variable and fact.table_id == group.table_id
    assert fact.geography == "state:15" and fact.vintage == config.vintage
    assert fact.source == "U.S. Census Bureau ACS 5-year"
    assert fact.endpoint == raw.endpoint and fact.label == raw.labels[variable]
    assert Fact.model_validate_json(fact.model_dump_json()) == fact
