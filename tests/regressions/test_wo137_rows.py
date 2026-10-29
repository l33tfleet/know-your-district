"""WO164: household outreach signals, comparable state basis, never a league table."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.analysis.reliability import classify
from app.copy import section_copy
from app.models import Fact
from etl.boundaries import Chamber
from etl.programs import load_catalog

ROOT = Path(__file__).resolve().parents[2]
VARIABLE = "B22003_006E"


def fact(geography: str, value: float | None, moe: float | None) -> Fact:
    cv, flag = classify(
        Decimal(str(value)) if value is not None else None,
        Decimal(str(moe)) if moe is not None else None,
    )
    return Fact(
        variable=VARIABLE,
        geography=geography,
        vintage="2020–2024",
        value=value,
        moe=moe,
        cv=float(cv) if cv is not None else None,
        reliability=flag,
        source="U.S. Census Bureau ACS 5-year",
        table_id="B22003",
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label="Households below poverty reporting no SNAP",
    )


@pytest.mark.parametrize("chamber,count", [("house", 51), ("senate", 25)])
def test_comparable_state_basis_and_no_league_ranking(chamber: Chamber, count: int) -> None:
    from app.analysis.outreach import OutreachRow, build_rows

    state = fact("state:15", 100 * count, 2 * count)
    districts = [
        fact(f"{chamber}:15:{n:03}:2022", v, 2)
        for n, v in [(3, 100), (1, 80), (count, 200), (2, 120)]
    ]
    inputs = {(f.variable, f.geography): f for f in [state, *districts]}
    result = build_rows(chamber, inputs, load_catalog(ROOT / "data/programs.yaml"))
    assert len(result.rows) == count
    assert [r.geography for r in result.rows] == [
        f"{chamber}:15:{n:03}:2022" for n in range(1, count + 1)
    ]
    assert {"rank", "position"}.isdisjoint(OutreachRow.model_fields)
    assert [r.group for r in result.rows[:3]] == ["lower", "higher", "indeterminate"]
    assert result.rows[-1].fact == districts[2]
    assert result.rows[-1].group == "higher"
    assert result.rows[0].fact == districts[1]  # published households, no subtraction
    basis = result.state_basis
    assert basis is not None
    assert (basis.value, basis.moe) == (100, 2)
    assert (basis.source, basis.table_id, basis.vintage, basis.geography, basis.endpoint) == (
        state.source,
        state.table_id,
        state.vintage,
        state.geography,
        state.endpoint,
    )
    assert "derived" in basis.method and str(count) in basis.method
    assert chamber.capitalize() in result.basis_label
    assert "average" in result.basis_label
    assert result.programs == tuple(load_catalog(ROOT / "data/programs.yaml")[:1])
    assert "households" in result.measure.lower()
    assert "undercount" in result.caveat and "national" in result.caveat
    assert "eligibility" in result.caveat


@pytest.mark.parametrize(
    "value,moe,state_value,state_moe,group",
    [
        (120, 2, 5100, 102, "higher"),
        (80, 2, 5100, 102, "lower"),
        (103, 2, 5100, 102, "indeterminate"),
        (103.29, 2, 5100, 0, "indeterminate"),  # strict > 1.645, not >=
        (103.30, 2, 5100, 0, "higher"),
        (100, 0, 5100, 0, "indeterminate"),
        (120, 0, 5100, 0, "higher"),
        (80, 0, 5100, 0, "lower"),
        (120, 80, 5100, 102, "caution"),
        (120, 2, 5100, 3000, "caution"),
        (0, 2, 5100, 102, "caution"),
        (120, None, 5100, 102, "caution"),
        (120, 2, 5100, None, "caution"),
        (120, 2, 0, 102, "caution"),
        (None, 2, 5100, 102, "missing"),
        (120, 2, None, 102, "missing"),
    ],
)
def test_comparison_contract(
    value: float | None,
    moe: float | None,
    state_value: float | None,
    state_moe: float | None,
    group: str,
) -> None:
    from app.analysis.outreach import build_rows

    district = fact("house:15:001:2022", value, moe)
    state = fact("state:15", state_value, state_moe)
    result = build_rows("house", {(f.variable, f.geography): f for f in [district, state]}, [])
    row = result.rows[0]
    assert row.group == group
    assert row.fact == district  # caution and unavailable facts remain inspectable
    assert row.reliability_word == section_copy("figures")["reliability"][district.reliability]
    assert row.comparison == section_copy("outreach")["groups"][group]


@pytest.mark.parametrize("absent", ["district", "state"])
def test_absent_rows_are_missing(absent: str) -> None:
    from app.analysis.outreach import build_rows

    district = fact("house:15:001:2022", 120, 2)
    state = fact("state:15", 5100, 102)
    remaining = state if absent == "district" else district
    result = build_rows("house", {(remaining.variable, remaining.geography): remaining}, [])
    assert result.rows[0].group == "missing"
    if absent == "district":
        assert result.rows[0].fact is None
        assert (
            result.rows[0].reliability_word == section_copy("figures")["reliability"]["unavailable"]
        )
    else:
        assert result.state_basis is None


def test_loader_reads_published_households_and_catalog_referrals() -> None:
    from app.analysis.outreach import load_rows
    from app.outreach_store import outreach_store

    result = load_rows("senate")
    published = outreach_store().get([(VARIABLE, "senate:15:001:2022")], "2020–2024")
    assert result.rows[0].fact == published[(VARIABLE, "senate:15:001:2022")]
    snap = result.programs[0]
    assert str(snap.official_url) == "https://humanservices.hawaii.gov/bessd/snap/"
    assert snap.referral_url == "https://www.auw211.org/"
    assert "agency decides eligibility" in snap.guidance


def test_different_vintages_cannot_be_grouped() -> None:
    from app.analysis.outreach import build_rows

    district = fact("house:15:001:2022", 120, 2).model_copy(update={"vintage": "2019–2023"})
    state = fact("state:15", 5100, 102)
    result = build_rows("house", {(f.variable, f.geography): f for f in [district, state]}, [])
    assert result.rows[0].group == "missing"
