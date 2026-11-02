"""#286: a malformed `data/cases.yaml` stops the server before it accepts a request.

Sections are found by AST and imported at render time, so `app.cases` would otherwise first
run on the first brief request. Start-up calls it; importing `app.main` does not.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app as asgi_app
from app.main import validate_startup

ROOT = Path(__file__).resolve().parents[2]


def test_cases_load_at_startup_not_on_import() -> None:
    program = (
        "import sys\n"
        "import app.main\n"
        "assert 'app.cases' not in sys.modules\n"
        "app.main.validate_startup()\n"
        "assert 'app.cases' in sys.modules\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_unknown_population_fails_startup_naming_the_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import cases

    document = yaml.safe_load(cases.CASES_PATH.read_text(encoding="utf-8"))
    document["cases"][0]["population"] = "no_such_population"
    bad = tmp_path / "cases.yaml"
    bad.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cases, "CASES_PATH", bad)
    with pytest.raises(ValueError, match="snap_no_receipt: unknown population"):
        validate_startup()
    with (
        pytest.raises(ValueError, match="snap_no_receipt: unknown population"),
        TestClient(asgi_app),
    ):
        pytest.fail("the server must not accept a request")


def test_shipped_cases_start_cleanly() -> None:
    with TestClient(asgi_app) as client:
        assert client.get("/healthz").status_code == 200
