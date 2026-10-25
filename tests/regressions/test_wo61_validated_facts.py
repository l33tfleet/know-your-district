"""WO61: raw ACS responses become cited facts with honest uncertainty."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.models import Fact
from etl.census import CensusBatch, CensusError, load_config
from etl.facts import facts_from_batch
from etl.indicators import INDICATORS

ROOT = Path(__file__).resolve().parents[2]
HOUSE = "state legislative district (lower chamber)"
SENATE = "state legislative district (upper chamber)"


def batch(
    name: str = "population", value: str | None = "100", moe: str | None = "10"
) -> CensusBatch:
    group = INDICATORS[name]
    config = load_config(ROOT / "config.toml")
    row: dict[str, str | None] = {"state": "15"}
    for variable in group.variables:
        row.update({variable: value, variable[:-1] + "M": moe})
        row.update({variable + "A": None, variable[:-1] + "MA": None})
    endpoint = config.base_url.format(year=config.year)
    if group.endpoint != "detailed":
        endpoint += "/" + group.endpoint
    return CensusBatch(
        endpoint,
        config.vintage,
        {v: config.labels[v].format(year=config.year) for v in group.variables},
        [row],
    )


@pytest.mark.parametrize(
    ("value", "moe", "flag", "cv"),
    [
        ("100", "24.675", "reliable", 0.15),
        ("100", "24.676", "moderate", None),
        ("100", "49.35", "moderate", 0.30),
        ("100", "49.351", "caution", None),
        ("0", "10", "caution", None),
        ("100", None, "caution", None),
        (None, "10", "unavailable", None),
    ],
)
def test_thresholds(value: str | None, moe: str | None, flag: str, cv: float | None) -> None:
    fact = facts_from_batch(INDICATORS["population"], batch(value=value, moe=moe), "state:15")[0]
    assert fact.reliability == flag
    if cv is not None:
        assert fact.cv == pytest.approx(cv)
    elif value in (None, "0") or moe is None:
        assert fact.cv is None


@pytest.mark.parametrize(
    "sentinel", ["-666666666", "-999999999", "-888888888", "-555555555", "-222222222"]
)
def test_sentinels_never_become_figures(sentinel: str) -> None:
    group = INDICATORS["population"]
    missing = facts_from_batch(group, batch(value=sentinel), "state:15")[0]
    assert missing.value is None and missing.cv is None
    assert missing.reliability == "unavailable"
    uncertain = facts_from_batch(group, batch(moe=sentinel), "state:15")[0]
    assert uncertain.value == 100 and uncertain.moe is None and uncertain.cv is None
    assert uncertain.reliability == "caution"
    assert ("controlled" if sentinel == "-555555555" else "not available") in uncertain.method


def test_annotations_and_provenance_survive_model_and_sql_roundtrips() -> None:
    raw = batch("median_gross_rent", "3501", "-555555555")
    raw.rows[0].update(B25064_001EA="3,500+", B25064_001MA="**")
    fact = facts_from_batch(INDICATORS["median_gross_rent"], raw, "state:15")[0]
    assert fact.estimate_annotation == "3,500+"
    assert fact.moe_annotation == "**"
    assert "3,500+" in fact.method and "controlled" in fact.method
    assert fact.source == "U.S. Census Bureau ACS 5-year"
    assert (fact.table_id, fact.vintage, fact.geography) == ("B25064", "2020–2024", "state:15")
    assert fact.endpoint == raw.endpoint and fact.label == raw.labels[fact.variable]
    assert "published" in fact.method and "90%" in fact.method
    assert Fact.model_validate_json(fact.model_dump_json()) == fact
    with sqlite3.connect(":memory:") as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        row = fact.model_dump()
        db.execute(
            f"INSERT INTO facts ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
        assert db.execute("SELECT estimate_annotation, moe_annotation FROM facts").fetchone() == (
            "3,500+",
            "**",
        )


@pytest.mark.parametrize("name", INDICATORS)
def test_all_published_components_keep_their_own_keys(name: str) -> None:
    group = INDICATORS[name]
    facts = facts_from_batch(group, batch(name), "state:15")
    assert [f.variable for f in facts] == list(group.variables)
    assert all(f.table_id == group.table_id and f.value == 100 for f in facts)


@pytest.mark.parametrize(
    "kind,count,prefix", [(HOUSE, 51, "house"), (SENATE, 25, "senate"), ("county", 4, "county")]
)
def test_exact_geography_sets(kind: str, count: int, prefix: str) -> None:
    raw = batch()
    codes = (
        ["001", "003", "007", "009"]
        if kind == "county"
        else [f"{i:03}" for i in range(1, count + 1)]
    )
    raw.rows[:] = [raw.rows[0] | {kind: code} for code in codes]
    if kind == "county":
        raw.rows.append(raw.rows[0] | {kind: "005"})
    facts = facts_from_batch(INDICATORS["population"], raw, kind + ":*")
    suffix = ":2022" if prefix in ("house", "senate") else ""
    assert {f.geography for f in facts} == {f"{prefix}:15:{code}{suffix}" for code in codes}
    for change in ("duplicate", "missing", "wrong", "state", "unpadded"):
        original = raw.rows.copy()
        if change == "duplicate":
            raw.rows[-1] = raw.rows[0].copy()
        elif change == "missing":
            raw.rows.pop(0)
        else:
            raw.rows[0] = raw.rows[0] | (
                {"state": "16"}
                if change == "state"
                else {kind: "999" if change == "wrong" else "1"}
            )
        with pytest.raises(CensusError):
            facts_from_batch(INDICATORS["population"], raw, kind + ":*")
        raw.rows[:] = original


@pytest.mark.parametrize("bad", ["NaN", "inf", "abc", "-1"])
@pytest.mark.parametrize("cell", ["value", "moe"])
def test_invalid_numeric_cells_fail_closed(bad: str, cell: str) -> None:
    with pytest.raises(CensusError):
        raw = batch(value=bad) if cell == "value" else batch(moe=bad)
        facts_from_batch(INDICATORS["population"], raw, "state:15")


def test_missing_cells_or_state_identity_fail_closed() -> None:
    for column in ("B01003_001E", "B01003_001M", "B01003_001EA", "B01003_001MA", "state"):
        raw = batch()
        del raw.rows[0][column]
        with pytest.raises(CensusError):
            facts_from_batch(INDICATORS["population"], raw, "state:15")


@pytest.mark.parametrize("field", ["endpoint", "vintage", "labels"])
def test_conversion_requires_provenance(field: str) -> None:
    raw = batch()
    raw = (
        replace(raw, labels={"B01003_001E": ""})
        if field == "labels"
        else replace(raw, **{field: ""})
    )
    with pytest.raises(CensusError):
        facts_from_batch(INDICATORS["population"], raw, "state:15")


def test_complete_load_has_2025_unique_published_facts() -> None:
    facts: list[Fact] = []
    for name, group in INDICATORS.items():
        for kind, codes in (
            ("state", ["15"]),
            ("county", ["001", "003", "005", "007", "009"]),
            (HOUSE, [f"{i:03}" for i in range(1, 52)]),
            (SENATE, [f"{i:03}" for i in range(1, 26)]),
        ):
            raw = batch(name)
            raw.rows[:] = [raw.rows[0] | {kind: code} for code in codes]
            facts.extend(
                facts_from_batch(group, raw, "state:15" if kind == "state" else kind + ":*")
            )
    assert len(facts) == len({(f.variable, f.geography, f.vintage) for f in facts}) == 2025
    assert len({f.geography for f in facts}) == 81


@pytest.mark.parametrize("change", ["empty", "duplicate", "foreign"])
def test_state_response_requires_exactly_hawaii(change: str) -> None:
    raw = batch()
    if change == "empty":
        raw.rows.clear()
    elif change == "duplicate":
        raw.rows.append(raw.rows[0].copy())
    else:
        raw.rows[0]["state"] = "16"
    with pytest.raises(CensusError):
        facts_from_batch(INDICATORS["population"], raw, "state:15")
