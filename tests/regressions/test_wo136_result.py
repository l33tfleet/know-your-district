"""WO160: SNAP results preserve joint household facts, uncertainty and all counties."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.analysis.reliability import FLAG_WORDS
from app.counties import load_mapping
from app.facts import FactStore, acs_config
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[2]
VARIABLE = "B22003_006E"


@pytest.mark.parametrize("chamber,number", [("house", 1), ("senate", 7)])
def test_snap_result_preserves_published_joint_cell(chamber: str, number: int) -> None:
    from app.snap import load_result

    district = DistrictId.model_validate({"chamber": chamber, "district": number})
    result = load_result(district)
    geographies = [
        district.fact_key,
        *(s.county for s in load_mapping()[district.fact_key]),
        "state:15",
    ]
    expected = FactStore(ROOT / "data/snap/facts.db").get(
        ((VARIABLE, g) for g in geographies), acs_config()[0]
    )
    readings = [result.district, *result.counties, result.state]
    assert [r.geography for r in readings] == geographies
    for reading in readings:
        fact = expected[VARIABLE, reading.geography]
        assert reading.fact == fact
        assert reading.value_text == f"{fact.value:,.0f}"
        assert reading.moe_text == f"±{fact.moe:,.0f}"
        assert reading.reliability_word == FLAG_WORDS[fact.reliability]
        assert reading.units == "households"
    assert result.period == "2020–2024"
    assert (
        "survey-reported receipt over the past 12 months, not current enrollment or eligibility"
        in result.measure_note
    )
    assert "undercount" in result.undercount_note
    assert "national Census poverty thresholds" in result.poverty_note
    assert "does not determine eligibility" in result.poverty_note
    assert result.referral is not None
    assert str(result.referral.official_url) == "https://humanservices.hawaii.gov/bessd/snap/"
    assert str(result.referral.fallback_url) == "https://auw211.org/"
    assert result.referral.verified_on.isoformat() == "2026-10-28"
    assert "DHS decides eligibility" in result.referral.notice
    assert len(result.referral.assistance) == 7
    assert "Molokaʻi" in result.referral.service_area_limit
    assert "$" not in result.model_dump_json()


def test_split_counties_are_separate_unweighted_published_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import snap

    mapping = load_mapping()
    district = DistrictId(chamber="senate", district=7)
    split = district.fact_key
    original_share = mapping[split][0]
    # Synthetic split: the committed map currently has only single-county entries.
    mapping[split] = [
        original_share.model_copy(update={"county": "county:15:003", "area_share": 0.25}),
        original_share.model_copy(update={"county": "county:15:009", "area_share": 0.75}),
    ]
    monkeypatch.setattr(snap, "load_mapping", lambda: mapping)
    result = snap.load_result(district)
    assert len(result.counties) == len(mapping[split])
    for reading, share in zip(result.counties, mapping[split], strict=True):
        original = FactStore(ROOT / "data/snap/facts.db").get(
            [(VARIABLE, share.county)], result.period
        )[VARIABLE, share.county]
        assert reading.fact == original
        assert reading.geography == share.county


@pytest.mark.parametrize(
    "missing", ["database", "district", "county", "state", "estimate", "moe", "zero"]
)
def test_snap_missing_inputs_and_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    from app import snap

    database = tmp_path / "facts.db"
    district = DistrictId(chamber="house", district=1)
    geography = district.fact_key
    if missing == "county":
        geography = load_mapping()[geography][0].county
    elif missing == "state":
        geography = "state:15"
    if missing != "database":
        shutil.copyfile(ROOT / "data/snap/facts.db", database)
        with sqlite3.connect(database) as db:
            if missing in {"district", "county", "state"}:
                db.execute("DELETE FROM facts WHERE geography = ?", [geography])
            else:
                column = "moe" if missing == "moe" else "value"
                value = 0 if missing == "zero" else None
                flag = "unavailable" if missing == "estimate" else "caution"
                db.execute(
                    f"UPDATE facts SET {column} = ?, cv = NULL, reliability = ? WHERE geography = ?",
                    [value, flag, geography],
                )
    monkeypatch.setattr(snap, "SNAP_DB", database)
    result = snap.load_result(district)
    readings = [result.district, *result.counties, result.state]
    assert len(readings) == len(load_mapping()[district.fact_key]) + 2
    affected = next(r for r in readings if r.geography == geography)
    if missing in {"database", "district", "county", "state"}:
        assert affected.fact is None
        assert affected.value_text == "not available"
        assert affected.reliability_word == "not available"
    elif missing == "estimate":
        assert affected.value_text == "not available"
        assert affected.reliability_word == "not available"
    elif missing == "moe":
        assert affected.moe_text == "no margin of error published"
        assert affected.reliability_word == "use with caution"
    else:
        assert affected.value_text == "0"
        assert affected.reliability_word == "use with caution"
    if missing == "database":
        assert all(r.fact is None for r in readings)
        assert not database.exists()


def test_missing_referrals_preserves_fact_and_safe_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import snap

    monkeypatch.setattr(snap, "REFERRALS_PATH", tmp_path / "absent.json")
    result = snap.load_result(DistrictId(chamber="house", district=1))
    assert result.district.fact is not None
    assert result.referral is None
    assert "may help" in result.referral_note
    assert "DHS decides eligibility" in result.referral_note
    assert "211" in result.referral_note
    assert result.official_url == "https://humanservices.hawaii.gov/bessd/snap/"
    assert result.referral_url == "https://auw211.org/"
