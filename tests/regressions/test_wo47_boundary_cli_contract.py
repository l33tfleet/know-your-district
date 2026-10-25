"""WO-47: offline CLI preserves chamber identity and requires it on every feature."""

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "wo47_boundaries.geojson"


def run_cli(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "etl.boundaries", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_cli_prints_distinct_canonical_keys_for_valid_fixture() -> None:
    result = run_cli(FIXTURE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["house-01", "senate-01"]
    assert result.stderr == ""


def test_cli_rejects_chamberless_feature_without_partial_keys(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del data["features"][1]["properties"]["chamber"]
    path = tmp_path / "chamberless.geojson"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = run_cli(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Boundary validation failed:" in result.stderr
    assert "chamber" in result.stderr
    assert "Traceback" not in result.stderr
