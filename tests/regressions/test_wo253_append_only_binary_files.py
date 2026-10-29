"""WO #253: `regressions-append-only` treats added non-Python files as neutral.

The checker crashed with `UnicodeDecodeError` on PR #245, which adds the binary
fixture `tests/regressions/fixtures/134_dotax.xlsx`, because it read every added
file as Python source. The work order's rule:
- "count replacement tests only from added `.py` files. Treat other added files
  (fixtures, data) as neutral: they add no tests and are never errors."
- "Edits, renames and deletions of existing files of any type under
  `tests/regressions/` stay errors, as now."
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / ".github" / "scripts" / "regressions_append_only.py"

# Not valid UTF-8: 0x8d is the byte the CI run failed on.
XLSX = b"PK\x03\x04\x14\x00\x8d\xff\xfe\x00binary\x00"
FIXTURE = "tests/regressions/fixtures/134_dotax.xlsx"

BASE_TEST = """\
def test_one() -> None:
    assert 1 == 1


def test_two() -> None:
    assert 2 == 2
"""
WITHOUT_ONE = "def test_two() -> None:\n    assert 2 == 2\n"
SUPERSEDES_ONE = "Supersedes: tests/regressions/test_a.py::test_one — spec changed\n"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, rel: str, data: bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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
    write(r, "tests/regressions/test_a.py", BASE_TEST.encode())
    write(r, "tests/regressions/fixtures/old.xlsx", XLSX)
    commit(r, "base")
    git(r, "checkout", "-q", "-b", "agent/7-change")
    return r


def run_check(repo: Path, issue_body: str = "") -> subprocess.CompletedProcess[str]:
    body_file = repo.parent / "issue_body.md"
    body_file.write_text(issue_body, encoding="utf-8")
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", "agent/7-change", "--issue-body", str(body_file)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def assert_clean_fail(result: subprocess.CompletedProcess[str]) -> None:
    """A rule failure (exit 1 with a FAIL line), not a crash."""
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr


def test_adding_binary_fixture_passes(repo: Path) -> None:
    write(repo, FIXTURE, XLSX)
    commit(repo, "add fixture")
    result = run_check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_adding_binary_fixture_with_new_test_file_passes(repo: Path) -> None:
    write(repo, FIXTURE, XLSX)
    write(repo, "tests/regressions/test_wo169_dotax.py", b"def test_x() -> None:\n    pass\n")
    commit(repo, "add fixture and test")
    result = run_check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_binary_fixture_is_not_a_replacement(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE.encode())
    write(repo, FIXTURE, XLSX)
    commit(repo, "supersede with only a fixture")
    result = run_check(repo, SUPERSEDES_ONE)
    assert_clean_fail(result)
    assert "only 0 new" in result.stdout


def test_non_python_text_file_adds_no_tests(repo: Path) -> None:
    # Only `.py` files count, even when another file's text parses as tests.
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE.encode())
    write(
        repo, "tests/regressions/fixtures/test_a_v2.txt", b"def test_one_v2() -> None:\n    pass\n"
    )
    commit(repo, "supersede with a text file")
    result = run_check(repo, SUPERSEDES_ONE)
    assert_clean_fail(result)
    assert "only 0 new" in result.stdout


def test_python_replacement_next_to_binary_fixture_counts(repo: Path) -> None:
    write(repo, "tests/regressions/test_a.py", WITHOUT_ONE.encode())
    write(repo, FIXTURE, XLSX)
    write(repo, "tests/regressions/test_a_v2.py", b"def test_one_v2() -> None:\n    pass\n")
    commit(repo, "supersede with a replacement")
    result = run_check(repo, SUPERSEDES_ONE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_modifying_existing_binary_fixture_fails(repo: Path) -> None:
    write(repo, "tests/regressions/fixtures/old.xlsx", XLSX + b"\x8d")
    commit(repo, "edit fixture")
    assert_clean_fail(run_check(repo))


def test_deleting_existing_binary_fixture_fails(repo: Path) -> None:
    git(repo, "rm", "-q", "tests/regressions/fixtures/old.xlsx")
    commit(repo, "delete fixture")
    assert_clean_fail(run_check(repo))


def test_renaming_existing_binary_fixture_fails(repo: Path) -> None:
    git(repo, "mv", "tests/regressions/fixtures/old.xlsx", "tests/regressions/fixtures/new.xlsx")
    commit(repo, "rename fixture")
    assert_clean_fail(run_check(repo))


def test_supersedes_naming_binary_fixture_still_fails(repo: Path) -> None:
    # A Supersedes line only lets a test leave a `.py` file; it never opens a fixture.
    write(repo, "tests/regressions/fixtures/old.xlsx", XLSX + b"\x8d")
    commit(repo, "edit fixture")
    result = run_check(repo, "Supersedes: tests/regressions/fixtures/old.xlsx::test_one\n")
    assert_clean_fail(result)
