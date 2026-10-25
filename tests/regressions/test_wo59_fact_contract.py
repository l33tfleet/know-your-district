"""WO59: preserve published cells and require an unambiguous, cited fact key."""

import sqlite3
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import Fact
from etl.indicators import INDICATORS

ROOT = Path(__file__).resolve().parents[2]
DIRECT = {
    "B01003_001E",
    "DP05_0024PE",
    "B19013_001E",
    "S1701_C03_001E",
    "S1701_C03_010E",
    "S2301_C04_001E",
    "B22010_002E",
    "S2201_C04_001E",
    "B19055_002E",
    "B19059_002E",
    "B25064_001E",
    "S2701_C05_001E",
    "S1810_C03_001E",
    "S1602_C04_001E",
    "B08201_002E",
}


def fact() -> dict[str, object]:
    # Synthetic validation fixture, never a published observation.
    return dict(
        variable="B01003_001E",
        geography="house:15:001:2022",
        vintage="2020–2024",
        value=100.0,
        moe=10.0,
        cv=10 / 1.645 / 100,
        reliability="reliable",
        source="U.S. Census Bureau ACS 5-year",
        table_id="B01003",
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label="Estimate!!Total",
    )


def test_all_groups_expand_without_losing_poverty_or_rent_components() -> None:
    assert len(INDICATORS) == 17
    assert INDICATORS["poverty_ratio"].variables == tuple(f"C17002_{i:03}E" for i in range(1, 9))
    assert INDICATORS["rent_burden"].variables == ("DP04_0141PE", "DP04_0142PE")
    variables = [v for group in INDICATORS.values() for v in group.variables]
    assert len(variables) == len(set(variables)) == 25
    assert set(variables) == DIRECT | {f"C17002_{i:03}E" for i in range(1, 9)} | {
        "DP04_0141PE",
        "DP04_0142PE",
    }
    for group in INDICATORS.values():
        for variable in group.variables:
            assert group.moe_variable(variable) == variable[:-1] + "M"
            assert group.table_id == variable.split("_")[0]
            assert group.endpoint in {"detailed", "profile", "subject"}


def test_vintage_is_pinned_and_contract_records_golden_mapping() -> None:
    config = tomllib.loads((ROOT / "config.toml").read_text())
    assert config["acs"]["year"] == 2024
    assert config["acs"]["vintage"] == "2020–2024"
    contract = (ROOT / "docs/data.md").read_text()
    for phrase in (
        "2,025",
        "25 published",
        "17 logical",
        "variable, geography, vintage",
        "DP04_0141PE",
        "WO-6",
    ):
        assert phrase in contract


def test_model_roundtrip_and_unavailable_is_never_zero() -> None:
    row = Fact.model_validate(fact())
    assert Fact.model_validate_json(row.model_dump_json()) == row
    missing = fact() | dict(value=None, moe=None, cv=None, reliability="unavailable")
    assert Fact.model_validate(missing).value is None
    with pytest.raises(ValidationError):
        Fact.model_validate(missing | dict(value=0.0))


@pytest.mark.parametrize(
    "field",
    [
        "variable",
        "geography",
        "vintage",
        "source",
        "table_id",
        "method",
        "endpoint",
        "label",
        "reliability",
    ],
)
def test_model_and_sql_require_provenance(field: str) -> None:
    for invalid in (None, "", "   "):
        with pytest.raises(ValidationError):
            Fact.model_validate(fact() | {field: invalid})
        with sqlite3.connect(":memory:") as db:
            db.executescript((ROOT / "data/schema.sql").read_text())
            with pytest.raises(sqlite3.IntegrityError):
                insert(db, fact() | {field: invalid})


def insert(db: sqlite3.Connection, row: dict[str, object]) -> None:
    columns = ", ".join(row)
    db.execute(
        f"INSERT INTO facts ({columns}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values())
    )


def test_unique_fact_key_includes_vintage_and_qualified_geography() -> None:
    with sqlite3.connect(":memory:") as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        insert(db, fact())
        with pytest.raises(sqlite3.IntegrityError):
            insert(db, fact())
        insert(db, fact() | dict(geography="senate:15:001:2022"))
        insert(db, fact() | dict(vintage="2019–2023"))
        assert db.execute("SELECT COUNT(*) FROM facts").fetchone() == (3,)


@pytest.mark.parametrize(
    "change",
    [
        dict(value=-666666666),
        dict(moe=-1),
        dict(cv=-1),
        dict(reliability="hidden"),
        dict(value=None),
        dict(value=0, cv=0, reliability="reliable"),
    ],
)
def test_model_and_sql_reject_invalid_numeric_states(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Fact.model_validate(fact() | change)
    with sqlite3.connect(":memory:") as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        with pytest.raises(sqlite3.IntegrityError):
            insert(db, fact() | change)
