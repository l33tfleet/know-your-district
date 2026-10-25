"""Offline boundary CLI reports invalid input without emitting partial keys."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "wo47_boundaries.geojson"


def run_cli(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "etl.boundaries", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize("problem", ["encoding", "json", "duplicate", "district"])
def test_cli_rejects_invalid_input_without_partial_keys(tmp_path: Path, problem: str) -> None:
    path = tmp_path / "boundaries.geojson"
    if problem == "encoding":
        path.write_bytes(b"\xff")
    elif problem == "json":
        path.write_text("{", encoding="utf-8")
    else:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        if problem == "duplicate":
            duplicate = json.loads(json.dumps(data["features"][0]))
            duplicate["properties"]["district"] = "01"
            data["features"].append(duplicate)
        else:
            data["features"][0]["properties"]["district"] = "052"
        path.write_text(json.dumps(data), encoding="utf-8")
    result = run_cli(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Boundary validation failed:" in result.stderr
    assert "Traceback" not in result.stderr
