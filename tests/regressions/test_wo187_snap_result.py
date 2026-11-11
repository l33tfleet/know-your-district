"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.analysis.reliability import FLAG_WORDS
from app.counties import load_mapping
from app.facts import FactStore, acs_config
from etl.boundaries import DistrictId
from tests.regressions.test_wo136_result import ROOT, VARIABLE

__all__ = ["ROOT", "VARIABLE"]

NA = "This figure is not available"


# Replaces test_wo136_result.py::test_snap_result_preserves_published_joint_cell (wording only, #187).
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
        "ACS asks if a household got SNAP in the past 12 months. This is not current "
        "enrollment or eligibility." in result.measure_note
    )
    assert "undercount" in result.undercount_note
    assert "national Census poverty thresholds" in result.poverty_note
    assert "does not decide who is eligible" in result.poverty_note
    assert result.referral is not None
    assert str(result.referral.official_url) == "https://humanservices.hawaii.gov/bessd/snap/"
    assert str(result.referral.fallback_url) == "https://auw211.org/"
    assert result.referral.verified_on.isoformat() == "2026-10-28"
    assert "DHS decides eligibility" in result.referral.notice
    assert len(result.referral.assistance) == 7
    assert "Molokaʻi" in result.referral.service_area_limit
    assert "$" not in result.model_dump_json()


# Replaces test_wo136_result.py::test_snap_missing_inputs_and_zero (wording only, #187).
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
        assert affected.value_text == NA
        assert affected.reliability_word == NA
    elif missing == "estimate":
        assert affected.value_text == NA
        assert affected.reliability_word == NA
    elif missing == "moe":
        assert affected.moe_text == "no margin of error published"
        assert affected.reliability_word == "use with caution"
    else:
        assert affected.value_text == "0"
        assert affected.reliability_word == "use with caution"
    if missing == "database":
        assert all(r.fact is None for r in readings)
        assert not database.exists()
