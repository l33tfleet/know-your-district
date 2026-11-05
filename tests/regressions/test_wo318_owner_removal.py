"""WO #318: a code owner may remove a rejected feature's regression file.

A comment on the Issue by an owner named in the base's .github/CODEOWNERS, with
a line `Removes: tests/regressions/FILE.py`, lets the PR delete that file, as
long as the PR adds at least one new regression test. Anyone else's comment
changes nothing, and other deletions still fail. (#312: the quiz Kevin rejected.)
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / ".github" / "scripts" / "regressions_append_only.py"
OLD = "tests/regressions/test_quiz.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "test@example.com")
    git(r, "config", "user.name", "Test")
    git(r, "config", "commit.gpgsign", "false")
    write(r, ".github/CODEOWNERS", "# formerly @ghost\n/.github/   @k7lim  # was @ghost2\n")
    write(r, OLD, "def test_ranks() -> None:\n    assert True\n")
    write(r, "tests/regressions/test_keep.py", "def test_keep() -> None:\n    assert True\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    git(r, "checkout", "-q", "-b", "agent/9-remove-quiz")
    return r


def change(repo: Path, *, delete: tuple[str, ...], add_test: bool) -> None:
    for rel in delete:
        (repo / rel).unlink()
    if add_test:
        write(
            repo,
            "tests/regressions/test_no_quiz.py",
            "def test_no_quiz() -> None:\n    assert True\n",
        )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "remove")


def run(repo: Path, comments: list[dict[str, str]]) -> subprocess.CompletedProcess[str]:
    body, notes = repo.parent / "body.md", repo.parent / "comments.json"
    body.write_text("Remove the quiz.\n", encoding="utf-8")
    notes.write_text(json.dumps(comments), encoding="utf-8")
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", "agent/9-remove-quiz", "--issue-body", str(body)]
    args += ["--issue-comments", str(notes)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_an_owner_comment_allows_removing_the_file(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    result = run(repo, [{"author": "k7lim", "body": f"Approved.\nRemoves: {OLD}\n"}])
    assert result.returncode == 0, result.stdout
    assert f"an owner removes {OLD}" in result.stdout


def test_owner_logins_match_without_case(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    assert run(repo, [{"author": "K7Lim", "body": f"Removes: `{OLD}`"}]).returncode == 0


def test_a_non_owner_comment_changes_nothing(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    result = run(repo, [{"author": "l33tfleet-merge-orchestrator", "body": f"Removes: {OLD}"}])
    assert result.returncode == 1
    assert "deleted; files under tests/regressions/ are append-only" in result.stdout


def test_a_removal_needs_a_new_test_pinning_it(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=False)
    result = run(repo, [{"author": "k7lim", "body": f"Removes: {OLD}"}])
    assert result.returncode == 1
    assert "no new top-level test" in result.stdout


def test_other_deletions_still_fail(repo: Path) -> None:
    change(repo, delete=(OLD, "tests/regressions/test_keep.py"), add_test=True)
    result = run(repo, [{"author": "k7lim", "body": f"Removes: {OLD}"}])
    assert result.returncode == 1
    assert "test_keep.py" in result.stdout


def test_a_comment_line_in_codeowners_names_no_owner(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    for former in ("ghost", "ghost2"):  # named only in CODEOWNERS comments
        result = run(repo, [{"author": former, "body": f"Removes: {OLD}"}])
        assert result.returncode == 1, former


def run_with_gh(repo: Path, script: str) -> subprocess.CompletedProcess[str]:
    """No --issue-body/--issue-comments: the checker asks `gh`, here a stub first on PATH."""
    bin_dir = repo.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + script, encoding="utf-8")
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", "agent/9-remove-quiz"]
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env)


def test_comments_fetched_with_gh_allow_an_owner_removal(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    line = json.dumps({"author": "k7lim", "body": f"Removes: {OLD}"})
    result = run_with_gh(
        repo, f"if [[ \"$*\" == *comments* ]]; then echo '{line}'; else echo body; fi\n"
    )
    assert result.returncode == 0, result.stdout
    assert f"an owner removes {OLD}" in result.stdout


def test_unreadable_comments_fall_back_to_the_strict_rule(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    result = run_with_gh(
        repo, 'if [[ "$*" == *comments* ]]; then echo nope >&2; exit 1; else echo body; fi\n'
    )
    assert result.returncode == 1
    assert "cannot read Issue #9's comments; no owner removals" in result.stdout
    assert "deleted; files under tests/regressions/ are append-only" in result.stdout


def test_missing_gh_falls_back_to_the_strict_rule(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    only_git = repo.parent / "only-git"  # git, but no gh
    only_git.mkdir()
    (only_git / "git").symlink_to(shutil.which("git") or "/usr/bin/git")
    env = {**os.environ, "PATH": str(only_git)}
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += ["--branch", "agent/9-remove-quiz"]
    result = subprocess.run(args, capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1
    assert "no owner removals" in result.stdout


def test_a_longer_name_does_not_authorize_its_prefix(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    result = run(repo, [{"author": "k7lim", "body": f"Removes: {OLD}.disabled"}])
    assert result.returncode == 1
    assert "deleted; files under tests/regressions/ are append-only" in result.stdout


def test_owners_come_from_the_base_not_the_pr(repo: Path) -> None:
    write(repo, ".github/CODEOWNERS", "/.github/   @k7lim @intruder\n")  # the PR names itself
    change(repo, delete=(OLD,), add_test=True)
    result = run(repo, [{"author": "intruder", "body": f"Removes: {OLD}"}])
    assert result.returncode == 1


def test_a_comment_with_windows_line_ends_still_counts(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    assert (
        run(repo, [{"author": "k7lim", "body": f"Approved.\r\nRemoves: {OLD}\r\n"}]).returncode == 0
    )


@pytest.mark.parametrize("text", [None, "not json", '{"author": "k7lim"}', "[1, 2]"])
def test_an_unreadable_comments_file_falls_back_to_the_strict_rule(
    repo: Path, text: str | None
) -> None:
    change(repo, delete=(OLD,), add_test=True)
    body, notes = repo.parent / "body.md", repo.parent / "comments.json"
    body.write_text("Remove the quiz.\n", encoding="utf-8")
    if text is not None:
        notes.write_text(text, encoding="utf-8")
    args = [sys.executable, str(CHECKER), "--repo", str(repo), "--base", "main", "--head", "HEAD"]
    args += [
        "--branch",
        "agent/9-remove-quiz",
        "--issue-body",
        str(body),
        "--issue-comments",
        str(notes),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stderr
    assert "Traceback" not in result.stderr
    assert "no owner removals" in result.stdout
    assert "deleted; files under tests/regressions/ are append-only" in result.stdout


def test_unparsable_gh_comments_fall_back_to_the_strict_rule(repo: Path) -> None:
    change(repo, delete=(OLD,), add_test=True)
    result = run_with_gh(
        repo, 'if [[ "$*" == *comments* ]]; then echo "{oops"; else echo body; fi\n'
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "cannot parse Issue #9's comments; no owner removals" in result.stdout
