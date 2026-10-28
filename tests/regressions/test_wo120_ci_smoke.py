"""WO120: CI smoke starts with an isolated fixture database on a clean checkout."""

import os
import socket
import subprocess
from pathlib import Path

from tests.regressions.test_wo41_smoke_step_stops_server import smoke_script

ROOT = Path(__file__).resolve().parents[2]


def test_ci_smoke_passes_without_deployed_database(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Exercise the actual workflow commands, with a free port and no deployed DB.
    script = smoke_script().replace("8000", str(port))
    script += '\nprintf "fixture-db=%s\\n" "$KYD_FACTS_DB"\n'
    missing = tmp_path / "absent.db"
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=ROOT,
        env={**os.environ, "KYD_FACTS_DB": str(missing), "TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for path in (
        "/healthz",
        "/",
        "/brief/house/22",
        "/brief/senate/1",
        "/static/vendor/htmx-2.0.11.min.js",
    ):
        assert f"GET http://127.0.0.1:{port}{path} -> 200" in result.stdout
    assert not missing.exists()
    database = Path(
        next(
            line.removeprefix("fixture-db=")
            for line in result.stdout.splitlines()
            if line.startswith("fixture-db=")
        )
    )
    assert database.parent == tmp_path
    assert not database.exists(), "CI must clean up its fixture database"
