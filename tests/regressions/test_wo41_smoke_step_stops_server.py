"""WO #41: the CI smoke step stops its background server, pass or fail.

A server left running holds uv's cache lock, and setup-uv's post step
(`uv cache prune --ci`) then times out and fails the `tests` job. The step's
script is run here under bash with stub `uv`, `curl` and `make` on PATH.
"""

import os
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


def run_step(tmp_path: Path, smoke_exit: int) -> tuple[int, int]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "server.pid"
    # `uv run uvicorn ...` stands in as a long-lived process that records its PID.
    stub(bin_dir, "uv", f'echo $$ > "{pid_file}"\nexec sleep 300\n')
    stub(bin_dir, "curl", "exit 0\n")
    stub(bin_dir, "make", f"exit {smoke_exit}\n")
    bash = shutil.which("bash")
    assert bash
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    # GitHub Actions runs `run:` steps as `bash -e {0}`. No output pipes: a
    # leftover server would hold them open and hang the test instead of failing it.
    result = subprocess.run(
        [bash, "-e", "-c", smoke_script()],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    return result.returncode, int(pid_file.read_text(encoding="utf-8").strip())


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie whose parent already exited is reaped by init; treat it as gone.
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split()[2] == "Z")


def stop(pid: int) -> None:
    if alive(pid):
        os.kill(pid, 9)


def test_server_is_stopped_when_smoke_passes(tmp_path: Path) -> None:
    code, pid = run_step(tmp_path, smoke_exit=0)
    try:
        assert code == 0
        assert not alive(pid), "smoke step left the server running"
    finally:
        stop(pid)


def test_server_is_stopped_and_job_fails_when_smoke_fails(tmp_path: Path) -> None:
    code, pid = run_step(tmp_path, smoke_exit=1)
    try:
        assert code != 0, "a failing smoke test must fail the step"
        assert not alive(pid), "smoke step left the server running after a failure"
    finally:
        stop(pid)
