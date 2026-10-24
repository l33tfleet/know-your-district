"""WO #3: the `regressions-append-only` check.

Pins the Notes of work order #3: diff the PR against its merge base and fail on
any modified, renamed or deleted file under `tests/regressions/`; the only
exception is a `Supersedes: PATH::TEST` line on the PR's Issue (number from the
`agent/<n>-` branch name), which lets that one top-level test, and nothing
else, leave its file, compared at the AST level.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / ".github" / "scripts" / "regressions_append_only.py"

BASE_TEST = """\
import math


def test_one() -> None:
    assert math.pi > 3


def test_two() -> None:
    assert math.e > 2
"""

WITHOUT_ONE = """\
import math


def test_two() -> None:
    assert math.e > 2
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "test@example.com")
    git(r, "config", "user.name", "Test")
    git(r, "config", "commit.gpgsign", "false")
    write(r, "tests/regressions/test_a.py", BASE_TEST)
    write(r, "app/main.py", "X = 1\n")
    commit(r, "base")
    git(r, "checkout", "-q", "-b", "agent/7-change")
    return r


def run_check(
    repo: Path, *, branch: str = "agent/7-change", issue_body: str | None = None
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", branch]
    if issue_body is not None:
        body_file = repo.parent / "issue_body.md"
        body_file.write_text(issue_body, encoding="utf-8")
        args += ["--issue-body", str(body_file)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_checker_exists() -> None:
    assert CHECKER.is_file()


def test_no_changes_passes(repo: Path) -> None:
    commit(repo, "nothing")
    assert run_check(repo, issue_body="").returncode == 0


def test_adding_new_files_passes(repo: Path) -> None:
    write(repo, "tests/regressions/test_b.py", "def test_b() -> None:\n    assert True\n")
    write(repo, "app/main.py", "X = 2\n")
    commit(repo, "add")
    result = run_check(repo, issue_body="")
    assert result.returncode == 0, result.stdout + result.stderr


def test_editing_existing_file_fails(repo: Path) -> None:
    write(
        repo, "tests/regressions/test_a.py", BASE_TEST + "\n\ndef test_three() -> None:\n    pass\n"
    )
    commit(repo, "edit")
    result = run_check(repo, issue_body="")
    assert result.returncode != 0
    assert "tests/regressions/test_a.py" in result.stdout + result.stderr


def test_whitespace_only_edit_fails(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", BASE_TEST + "\n")
    commit(repo, "ws")
    assert run_check(repo, issue_body="").returncode != 0


def test_renaming_existing_file_fails(repo: Path) -> None:
    git(repo, "mv", "tests/regressions/test_a.py", "tests/regressions/test_renamed.py")
    commit(repo, "rename")
    assert run_check(repo, issue_body="").returncode != 0


def test_moving_file_out_of_regressions_fails(repo: Path) -> None:
    git(repo, "mv", "tests/regressions/test_a.py", "tests/test_a.py")
    commit(repo, "move")
    assert run_check(repo, issue_body="").returncode != 0


def test_deleting_existing_file_fails(repo: Path) -> None:
    git(repo, "rm", "-q", "tests/regressions/test_a.py")
    commit(repo, "delete")
    assert run_check(repo, issue_body="").returncode != 0


def test_uses_merge_base_not_base_tip(repo: Path) -> None:
    # main gains a regression file after the branch forked; the branch lacks it,
    # which must not count as a deletion.
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/regressions/test_later.py", "def test_later() -> None:\n    pass\n")
    commit(repo, "main moves on")
    git(repo, "checkout", "-q", "agent/7-change")
    write(repo, "app/main.py", "X = 3\n")
    commit(repo, "branch work")
    result = run_check(repo, issue_body="")
    assert result.returncode == 0, result.stdout + result.stderr


SUPERSEDES_ONE = "Some text\n\nSupersedes: tests/regressions/test_a.py::test_one — spec changed\n"


def test_supersedes_allows_deleting_only_that_test(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    write(repo, "tests/regressions/test_a_v2.py", "def test_one_v2() -> None:\n    pass\n")
    commit(repo, "supersede")
    result = run_check(repo, issue_body=SUPERSEDES_ONE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_supersedes_accepts_backticked_line(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    write(repo, "tests/regressions/test_a_v2.py", "def test_one_v2() -> None:\n    pass\n")
    commit(repo, "supersede")
    body = "Supersedes: `tests/regressions/test_a.py::test_one`\n"
    assert run_check(repo, issue_body=body).returncode == 0


def test_supersedes_ignores_comment_only_differences(repo: Path) -> None:
    # AST-level comparison: removing the test may take its blank lines along.
    write(
        repo,
        "tests/regressions/test_a.py",
        "import math\n\n\ndef test_two() -> None:\n    assert math.e > 2\n",
    )
    write(repo, "tests/regressions/test_a_v2.py", "def test_one_v2() -> None:\n    pass\n")
    commit(repo, "supersede")
    assert run_check(repo, issue_body=SUPERSEDES_ONE).returncode == 0


def test_deleting_test_without_supersedes_fails(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    commit(repo, "delete test")
    assert run_check(repo, issue_body="").returncode != 0


def test_supersedes_on_wrong_test_fails(repo: Path) -> None:
    write(
        repo,
        "tests/regressions/test_a.py",
        "import math\n\n\ndef test_one() -> None:\n    assert math.pi > 3\n",
    )
    commit(repo, "deletes test_two instead")
    assert run_check(repo, issue_body=SUPERSEDES_ONE).returncode != 0


def test_supersedes_with_extra_added_statement_fails(repo: Path) -> None:
    # Any other added statement could rebind or remove tests at import time.
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE + "\ntest_two = None\n")
    commit(repo, "sneaky")
    assert run_check(repo, issue_body=SUPERSEDES_ONE).returncode != 0


def test_supersedes_with_modified_other_test_fails(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE.replace("> 2", "> 0"))
    commit(repo, "weaken")
    assert run_check(repo, issue_body=SUPERSEDES_ONE).returncode != 0


def test_supersedes_with_changed_import_fails(repo: Path) -> None:
    write(
        repo,
        "tests/regressions/test_a.py",
        WITHOUT_ONE.replace("import math", "import cmath as math"),
    )
    commit(repo, "swap import")
    assert run_check(repo, issue_body=SUPERSEDES_ONE).returncode != 0


def test_supersedes_does_not_allow_deleting_whole_file(repo: Path) -> None:
    git(repo, "rm", "-q", "tests/regressions/test_a.py")
    commit(repo, "delete file")
    body = SUPERSEDES_ONE + "Supersedes: tests/regressions/test_a.py::test_two\n"
    assert run_check(repo, issue_body=body).returncode != 0


def test_supersedes_does_not_allow_rename(repo: Path) -> None:
    git(repo, "mv", "tests/regressions/test_a.py", "tests/regressions/test_b.py")
    commit(repo, "rename")
    assert run_check(repo, issue_body=SUPERSEDES_ONE).returncode != 0


def test_supersedes_needs_matching_branch(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    commit(repo, "supersede")
    result = run_check(repo, branch="feature/no-issue", issue_body=SUPERSEDES_ONE)
    assert result.returncode != 0


def test_supersedes_for_other_file_does_not_apply(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    commit(repo, "supersede")
    body = "Supersedes: tests/regressions/test_other.py::test_one\n"
    assert run_check(repo, issue_body=body).returncode != 0


def test_supersedes_only_top_level_tests(repo: Path) -> None:
    # A non-test top-level name cannot be superseded.
    write(repo, "tests/regressions/test_a.py", BASE_TEST.replace("import math\n", ""))
    commit(repo, "drop import")
    body = "Supersedes: tests/regressions/test_a.py::math\n"
    assert run_check(repo, issue_body=body).returncode != 0
