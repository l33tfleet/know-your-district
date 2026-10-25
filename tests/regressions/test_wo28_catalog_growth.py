"""WO #81 / #28: keep offline catalog validation compatible with growth."""

import subprocess
import sys
from pathlib import Path
from shutil import copyfile

import pytest
import yaml

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


def test_catalog_growth_preserves_offline_regressions(tmp_path: Path) -> None:
    programs = load_catalog(CATALOG)
    entries = [program.model_dump(mode="json") for program in programs]
    entries.extend(
        dict(entries[0], name=f"Synthetic catalog growth fixture {index}") for index in range(23)
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    catalog = data_dir / "programs.yaml"
    catalog.write_text(yaml.safe_dump(entries), encoding="utf-8")
    assert len(load_catalog(catalog)) == len(entries)

    # Run both the retained suite and replacement validation against growth.
    # The superseded exact-cardinality check makes this fail on main.
    test_dir = tmp_path / "tests" / "regressions"
    test_dir.mkdir(parents=True)
    suite = test_dir / "test_wo52_program_catalog.py"
    copyfile(Path(__file__).with_name(suite.name), suite)
    replacement = test_dir / Path(__file__).name
    copyfile(Path(__file__), replacement)
    root = CATALOG.parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "pyproject.toml"),
            str(suite),
            f"{replacement}::test_committed_catalog_validates_offline",
            "-q",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # A malformed last entry must fail too: validation cannot stop at SNAP and GA.
    del entries[-1]["official_url"]
    catalog.write_text(yaml.safe_dump(entries), encoding="utf-8")
    with pytest.raises(ValueError, match="official_url"):
        load_catalog(catalog)
