"""Fail a PR that modifies, renames or deletes an existing file under tests/regressions/.

The PR is diffed against its merge base with the base branch. New files pass.

One exception lets a spec change: the PR's Issue (number from the `agent/<n>-`
branch name) may carry `Supersedes: PATH::TEST` lines. Each named top-level
test may be deleted from its file, and that file may lose only that test,
compared at the AST level. Renames and whole-file deletions are never allowed.
Each deleted test needs a replacement: the PR's new files under
tests/regressions/ must add at least one new top-level test per superseded
test. Whether a replacement is at least as strict is left to the reviewer.
Paths are read NUL-delimited (`-z`), so names Git would quote are still caught.

Usage:
    regressions_append_only.py --base REF --head REF --branch NAME [--issue-body FILE] [--repo DIR]

Without --issue-body, the Issue body is fetched with `gh issue view <n>`.
"""

import argparse
import ast
import contextlib
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REGRESSIONS = "tests/regressions/"
BRANCH_RE = re.compile(r"^agent/(\d+)-")
SUPERSEDES_RE = re.compile(
    r"^\s*[-*]?\s*Supersedes:\s*`?([^`\s:]+)::([A-Za-z_]\w*)`?", re.MULTILINE
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def issue_number(branch: str) -> int | None:
    match = BRANCH_RE.match(branch)
    return int(match.group(1)) if match else None


def parse_supersedes(body: str) -> dict[str, set[str]]:
    allowed: dict[str, set[str]] = defaultdict(set)
    for path, test in SUPERSEDES_RE.findall(body):
        allowed[path.removeprefix("./")].add(test)
    return dict(allowed)


def fetch_issue_body(number: int) -> str:
    return subprocess.run(
        ["gh", "issue", "view", str(number), "--json", "body", "--jq", ".body"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_name(node: ast.stmt) -> str | None:
    """The name of a top-level pytest test function or class, else None."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
        return node.name
    if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
        return node.name
    return None


def top_level_tests(source: str) -> list[str]:
    return [name for node in ast.parse(source).body if (name := test_name(node))]


def check_superseded(path: str, old: str, new: str, tests: set[str]) -> tuple[list[str], int]:
    """The new file must equal the old one minus exactly the named top-level tests.

    Returns the errors and how many superseded tests the file actually lost.
    """
    try:
        old_body = ast.parse(old).body
        new_body = ast.parse(new).body
    except SyntaxError as err:
        return [f"{path}: cannot parse ({err})"], 0
    errors: list[str] = []
    found = {name for node in old_body if (name := test_name(node))}
    for test in sorted(tests - found):
        errors.append(f"{path}: Supersedes names {test}, which is not a top-level test in the base")
    kept = [node for node in old_body if test_name(node) not in tests]
    if [ast.dump(n) for n in kept] != [ast.dump(n) for n in new_body]:
        errors.append(
            f"{path}: may only lose the superseded tests ({', '.join(sorted(tests))}); "
            "any other change is not allowed"
        )
    return errors, len(old_body) - len(kept)


def name_status(repo: Path, merge_base: str, head: str) -> list[tuple[str, list[str]]]:
    """`git diff --name-status -z` as (status, paths), so no path is ever quoted."""
    raw = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--name-status",
            "-z",
            "-M",
            "--no-ext-diff",
            merge_base,
            head,
        ],
        check=True,
        capture_output=True,
    ).stdout
    fields = raw.decode("utf-8", "surrogateescape").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    entries: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        count = 2 if status[0] in "RC" else 1
        entries.append((status, fields[i + 1 : i + 1 + count]))
        i += 1 + count
    return entries


def check(repo: Path, base: str, head: str, supersedes: dict[str, set[str]]) -> list[str]:
    merge_base = git(repo, "merge-base", base, head).strip()
    errors: list[str] = []
    superseded = 0
    new_tests = 0
    for status, paths in name_status(repo, merge_base, head):
        kind = status[0]
        old_path = paths[0]
        new_path = paths[-1]
        added_here = kind in "AC" or (kind == "R" and not old_path.startswith(REGRESSIONS))
        if added_here and new_path.startswith(REGRESSIONS):
            # An unparsable new file adds no replacement tests.
            with contextlib.suppress(SyntaxError):
                new_tests += len(top_level_tests(git(repo, "show", f"{head}:{new_path}")))
        if kind in "AC" or not old_path.startswith(REGRESSIONS):
            continue
        if kind == "R":
            errors.append(
                f"{old_path!r}: renamed to {new_path!r}; files under {REGRESSIONS} are append-only"
            )
        elif kind == "D":
            errors.append(f"{old_path!r}: deleted; files under {REGRESSIONS} are append-only")
        elif kind == "M" and old_path in supersedes:
            old = git(repo, "show", f"{merge_base}:{old_path}")
            new = git(repo, "show", f"{head}:{old_path}")
            file_errors, lost = check_superseded(old_path, old, new, supersedes[old_path])
            errors.extend(file_errors)
            superseded += lost
        else:
            errors.append(
                f"{old_path!r}: modified; files under {REGRESSIONS} are append-only "
                "(put new tests in a new file, or name the superseded test on the Issue)"
            )
    if new_tests < superseded:
        errors.append(
            f"{superseded} superseded test(s) deleted but only {new_tests} new top-level "
            f"test(s) added in new files under {REGRESSIONS}; each superseded test needs a "
            "replacement in a new file"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--base", required=True, help="base branch ref or SHA")
    parser.add_argument("--head", required=True, help="PR head ref or SHA")
    parser.add_argument("--branch", required=True, help="PR head branch name, e.g. agent/12-foo")
    parser.add_argument(
        "--issue-body", type=Path, help="file holding the Issue body (else fetched with gh)"
    )
    args = parser.parse_args(argv)

    supersedes: dict[str, set[str]] = {}
    number = issue_number(args.branch)
    if number is not None:
        if args.issue_body is not None:
            body = args.issue_body.read_text(encoding="utf-8")
        else:
            body = fetch_issue_body(number)
        supersedes = parse_supersedes(body)
        for path, tests in sorted(supersedes.items()):
            print(f"Issue #{number} supersedes {path}::{', '.join(sorted(tests))}")

    errors = check(args.repo, args.base, args.head, supersedes)
    for error in errors:
        print(f"FAIL {error}")
    if not errors:
        print(f"ok  no existing file under {REGRESSIONS} was modified, renamed or deleted")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
