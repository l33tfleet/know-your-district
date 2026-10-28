"""WO120: CI cleanup preserves smoke failures and reports unexpected server exits."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.regressions.test_wo41_smoke_step_stops_server import smoke_script, stub

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("server_exit", "smoke_exit", "expected"),
    [(0, 0, 0), (42, 0, 42), (0, 7, 7), (42, 7, 7)],
    ids=[
        "clean-server-exit",
        "unexpected-server-failure",
        "preserve-smoke-failure",
        "smoke-failure-takes-precedence",
    ],
)
def test_ci_cleanup_preserves_failure_status(
    tmp_path: Path, server_exit: int, smoke_exit: int, expected: int
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Fixture DB creation and cleanup use real commands.
    stub(bin_dir, "uv", f"exit {server_exit}\n")
    stub(bin_dir, "curl", "exit 0\n")
    # Give the stub server time to exit before the step reaches its EXIT trap.
    stub(bin_dir, "make", f"sleep 0.2\nexit {smoke_exit}\n")
    result = subprocess.run(
        ["bash", "-e", "-c", smoke_script()],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == [bin_dir], "cleanup must remove the fixture DB"
