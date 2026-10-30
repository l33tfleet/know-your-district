"""WO #81 / #28: keep offline catalog validation compatible with growth."""

# Append-only rules require retaining imports from the superseded tests.
import subprocess  # noqa: F401 # pyright: ignore[reportUnusedImport]
import sys  # noqa: F401 # pyright: ignore[reportUnusedImport]
from pathlib import Path
from shutil import copyfile  # noqa: F401 # pyright: ignore[reportUnusedImport]

import pytest  # noqa: F401 # pyright: ignore[reportUnusedImport]
import yaml  # noqa: F401 # pyright: ignore[reportUnusedImport]
from pydantic import ValidationError  # noqa: F401 # pyright: ignore[reportUnusedImport]

from etl.programs import load_catalog

CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


def test_committed_catalog_validates_offline() -> None:
    programs = load_catalog(CATALOG)
    assert len(programs) >= 2
    assert programs[0].name == "Supplemental Nutrition Assistance Program (SNAP)"
    assert programs[1].name == "General Assistance (GA)"
    assert {p.eligibility_proxy.status for p in programs} == {"available", "unavailable"}
    for program in programs:
        assert "may help" in program.purpose
        assert "agency decides eligibility" in program.guidance.lower()
        assert str(program.referral_url) == "https://www.auw211.org/"
