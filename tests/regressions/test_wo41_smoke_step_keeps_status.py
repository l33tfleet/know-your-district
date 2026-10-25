"""WO #41, round 2: stopping the smoke server never hides a failure.

The cleanup that stops the background server must not swallow errors
(`|| true`, `|| :`, `set +e`), and the step must exit with the smoke test's
own status, whatever the stopped server's exit code is.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
STEP = "- name: Smoke test a running app"


def smoke_script() -> str:
    lines = CI.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == STEP)
    run = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


def stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def run_step(tmp_path: Path, smoke_exit: int) -> int:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # The stand-in server dies of SIGTERM, so its own exit code is non-zero.
    stub(bin_dir, "uv", "exec sleep 300\n")
    stub(bin_dir, "curl", "exit 0\n")
    stub(bin_dir, "make", f"exit {smoke_exit}\n")
    bash = shutil.which("bash")
    assert bash
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        [bash, "-e", "-c", smoke_script()],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    return result.returncode


def test_smoke_step_has_no_error_swallowing_construct() -> None:
    script = smoke_script()
    assert not re.search(r"\|\|\s*(true|:)(\s|;|'|\"|$)", script, re.MULTILINE)
    assert not re.search(r"\bset\s+\+e\b", script)


def test_step_exits_zero_when_smoke_passes(tmp_path: Path) -> None:
    assert run_step(tmp_path, smoke_exit=0) == 0


def test_step_exits_with_the_smoke_status_when_smoke_fails(tmp_path: Path) -> None:
    assert run_step(tmp_path, smoke_exit=7) == 7
