"""WO160: SNAP results preserve joint household facts, uncertainty and all counties."""

import shutil  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
import sqlite3  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from pathlib import Path

import pytest

from app.analysis.reliability import FLAG_WORDS  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from app.counties import load_mapping
from app.facts import FactStore, acs_config  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[2]
VARIABLE = "B22003_006E"


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
