"""#286: a malformed data/cases.yaml stops the server before it accepts a request.

Section modules load only at render time, so without a call from validate_startup the
cases would first be read by the first brief. The check runs at start-up, not on import.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app import cases
from app.main import app, validate_startup

ROOT = Path(__file__).resolve().parents[2]
PROBE = """
import sys
import app.main
assert "app.cases" not in sys.modules, "importing app.main must not validate the cases"
app.main.validate_startup()
assert "app.cases" in sys.modules, "validate_startup must validate the cases"
"""


def malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the cases path at the shipped record with an unknown population id."""
    data: dict[str, Any] = yaml.safe_load(cases.CASES_PATH.read_text(encoding="utf-8"))
    data["cases"][0]["population"] = "no_such_population"
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cases, "CASES_PATH", path)


def test_cases_are_checked_at_startup_not_on_import() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_validate_startup_names_the_bad_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=r"snap_poverty_no_receipt.*no_such_population"):
        validate_startup()


def test_malformed_cases_stop_lifespan_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="no_such_population"), TestClient(app):
        pytest.fail("the server must not start on a malformed cases file")


def test_shipped_cases_start_cleanly() -> None:
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
