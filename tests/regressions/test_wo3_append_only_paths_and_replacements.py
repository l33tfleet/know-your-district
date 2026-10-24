"""WO #3: `regressions-append-only` holds for any file name, and a Supersedes
deletion needs its replacement.

Pins two parts of the work order's Notes that the first checker missed:
- "fail on any modified, renamed or deleted file under `tests/regressions/`":
  that includes names Git quotes in its default output (non-ASCII, tabs,
  quotes), such as a file named after Hawaiʻi.
- "The replacement test goes in a new file": a superseded test may leave its
  file only if newly added files under `tests/regressions/` carry at least one
  new top-level test per superseded test.
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

WITHOUT_BOTH = "import math\n"

REPLACEMENT = "def test_one_v2() -> None:\n    assert 1 + 1 == 2\n"

# Names Git quotes in `--name-status` output unless -z is used.
QUOTED_NAMES = [
    "tests/regressions/test_hawaiʻi.py",
    'tests/regressions/test_"quoted".py',
    "tests/regressions/test_tab\there.py",
    "tests/regressions/test_back\\slash.py",
]


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


def make_repo(tmp_path: Path, rel: str) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "test@example.com")
    git(r, "config", "user.name", "Test")
    git(r, "config", "commit.gpgsign", "false")
    git(r, "config", "core.quotePath", "true")
    write(r, rel, BASE_TEST)
    write(r, "app/main.py", "X = 1\n")
    commit(r, "base")
    git(r, "checkout", "-q", "-b", "agent/7-change")
    return r


def run_check(repo: Path, issue_body: str) -> subprocess.CompletedProcess[str]:
    body_file = repo.parent / "issue_body.md"
    body_file.write_text(issue_body, encoding="utf-8")
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", "agent/7-change", "--issue-body", str(body_file)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("rel", QUOTED_NAMES)
def test_editing_file_with_quoted_name_fails(tmp_path: Path, rel: str) -> None:
    repo = make_repo(tmp_path, rel)
    write(repo, rel, BASE_TEST + "\n\ndef test_three() -> None:\n    pass\n")
    commit(repo, "edit")
    result = run_check(repo, "")
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("rel", QUOTED_NAMES)
def test_renaming_file_with_quoted_name_fails(tmp_path: Path, rel: str) -> None:
    repo = make_repo(tmp_path, rel)
    git(repo, "mv", rel, "tests/regressions/test_plain.py")
    commit(repo, "rename")
    result = run_check(repo, "")
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("rel", QUOTED_NAMES)
def test_deleting_file_with_quoted_name_fails(tmp_path: Path, rel: str) -> None:
    repo = make_repo(tmp_path, rel)
    git(repo, "rm", "-q", rel)
    commit(repo, "delete")
    result = run_check(repo, "")
    assert result.returncode != 0, result.stdout + result.stderr


def test_supersedes_works_for_non_ascii_name(tmp_path: Path) -> None:
    rel = "tests/regressions/test_hawaiʻi.py"
    repo = make_repo(tmp_path, rel)
    write(repo, rel, WITHOUT_ONE)
    write(repo, "tests/regressions/test_hawaiʻi_v2.py", REPLACEMENT)
    commit(repo, "supersede")
    result = run_check(repo, f"Supersedes: {rel}::test_one\n")
    assert result.returncode == 0, result.stdout + result.stderr


SUPERSEDES_ONE = "Supersedes: tests/regressions/test_a.py::test_one — spec changed\n"
SUPERSEDES_BOTH = SUPERSEDES_ONE + "Supersedes: tests/regressions/test_a.py::test_two\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path, "tests/regressions/test_a.py")


def test_supersedes_without_replacement_fails(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    commit(repo, "supersede, no replacement")
    result = run_check(repo, SUPERSEDES_ONE)
    assert result.returncode != 0
    assert "replacement" in result.stdout


def test_supersedes_with_replacement_in_new_file_passes(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    write(repo, "tests/regressions/test_a_v2.py", REPLACEMENT)
    commit(repo, "supersede")
    result = run_check(repo, SUPERSEDES_ONE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_replacement_file_without_tests_fails(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    write(repo, "tests/regressions/test_a_v2.py", "X = 1\n\n\ndef helper() -> None:\n    pass\n")
    commit(repo, "empty replacement")
    assert run_check(repo, SUPERSEDES_ONE).returncode != 0


def test_replacement_outside_regressions_fails(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE)
    write(repo, "tests/test_a_v2.py", REPLACEMENT)
    commit(repo, "replacement in the wrong place")
    assert run_check(repo, SUPERSEDES_ONE).returncode != 0


def test_replacement_added_to_existing_file_fails(repo: Path) -> None:
    # The replacement must go in a new file, not into the superseded test's file.
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE + "\n\n" + REPLACEMENT)
    commit(repo, "replacement in the old file")
    assert run_check(repo, SUPERSEDES_ONE).returncode != 0


def test_two_superseded_tests_need_two_replacements(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_BOTH)
    write(repo, "tests/regressions/test_a_v2.py", REPLACEMENT)
    commit(repo, "one replacement for two")
    assert run_check(repo, SUPERSEDES_BOTH).returncode != 0


def test_two_superseded_tests_with_two_replacements_pass(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_BOTH)
    write(repo, "tests/regressions/test_a_v2.py", REPLACEMENT)
    write(repo, "tests/regressions/test_a_v3.py", "def test_two_v2() -> None:\n    pass\n")
    commit(repo, "two replacements")
    result = run_check(repo, SUPERSEDES_BOTH)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unused_supersedes_line_needs_no_replacement(repo: Path) -> None:
    # Naming a test on the Issue without deleting it changes nothing.
    write(repo, "app/main.py", "X = 2\n")
    commit(repo, "unrelated work")
    result = run_check(repo, SUPERSEDES_ONE)
    assert result.returncode == 0, result.stdout + result.stderr
