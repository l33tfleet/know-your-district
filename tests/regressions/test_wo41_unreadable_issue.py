"""WO #41: `regressions_append_only.py` with an Issue body it cannot read.

When `gh issue view` fails (e.g. the Issue isn't visible to the Actions token),
the checker treats the Issue as having no `Supersedes:` lines, i.e. the strict
rule, prints a one-line notice, and never crashes. A stub `gh` that always
fails is put first on PATH.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / ".github" / "scripts" / "regressions_append_only.py"

BASE_TEST = """\
def test_one() -> None:
    assert True


def test_two() -> None:
    assert True
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "test@example.com")
    git(r, "config", "user.name", "Test")
    git(r, "config", "commit.gpgsign", "false")
    write(r, "tests/regressions/test_a.py", BASE_TEST)
    commit(r, "base")
    git(r, "checkout", "-q", "-b", "agent/7-change")
    return r


def run_with_failing_gh(repo: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = repo.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\necho 'GraphQL: Could not resolve to an issue' >&2\nexit 1\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", "agent/7-change"]
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env)


def test_unreadable_issue_still_fails_a_modified_regression_file(repo: Path) -> None:
    write(
        repo, "tests/regressions/test_a.py", BASE_TEST + "\n\ndef test_three() -> None:\n    pass\n"
    )
    commit(repo, "edit")
    result = run_with_failing_gh(repo)
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "Traceback" not in out
    assert "tests/regressions/test_a.py" in result.stdout


def test_unreadable_issue_does_not_allow_deleting_a_test(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", "def test_two() -> None:\n    assert True\n")
    write(repo, "tests/regressions/test_b.py", "def test_b() -> None:\n    assert True\n")
    commit(repo, "drop test_one")
    result = run_with_failing_gh(repo)
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "Traceback" not in out


def test_unreadable_issue_passes_new_files_with_one_line_notice(repo: Path) -> None:
    write(repo, "tests/regressions/test_b.py", "def test_b() -> None:\n    assert True\n")
    commit(repo, "add")
    result = run_with_failing_gh(repo)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "Traceback" not in out
    notices = [line for line in out.splitlines() if "#7" in line]
    assert len(notices) == 1, out
    assert "Supersedes" in notices[0]
