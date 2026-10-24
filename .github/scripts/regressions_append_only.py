"""Fail a PR that modifies, renames or deletes an existing file under tests/regressions/.

The PR is diffed against its merge base with the base branch. New files pass.

One exception lets a spec change: the PR's Issue (number from the `agent/<n>-`
branch name) may carry `Supersedes: PATH::TEST` lines. Each named top-level
test may be deleted from its file, and that file may lose only that test,
compared at the AST level. Renames and whole-file deletions are never allowed.

Usage:
    regressions_append_only.py --base REF --head REF --branch NAME [--issue-body FILE] [--repo DIR]

Without --issue-body, the Issue body is fetched with `gh issue view <n>`.
"""

import argparse
import ast
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


def check_superseded(path: str, old: str, new: str, tests: set[str]) -> list[str]:
    """The new file must equal the old one minus exactly the named top-level tests."""
    try:
        old_body = ast.parse(old).body
        new_body = ast.parse(new).body
    except SyntaxError as err:
        return [f"{path}: cannot parse ({err})"]
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
    return errors


def check(repo: Path, base: str, head: str, supersedes: dict[str, set[str]]) -> list[str]:
    merge_base = git(repo, "merge-base", base, head).strip()
    diff = git(repo, "diff", "--name-status", "-M", "--no-ext-diff", merge_base, head)
    errors: list[str] = []
    for line in diff.splitlines():
        status, *paths = line.split("\t")
        kind = status[0]
        old_path = paths[0]
        if kind in "AC":
            continue
        if not old_path.startswith(REGRESSIONS):
            continue
        if kind == "R":
            errors.append(
                f"{old_path}: renamed to {paths[1]}; files under {REGRESSIONS} are append-only"
            )
        elif kind == "D":
            errors.append(f"{old_path}: deleted; files under {REGRESSIONS} are append-only")
        elif kind == "M" and old_path in supersedes:
            old = git(repo, "show", f"{merge_base}:{old_path}")
            new = git(repo, "show", f"{head}:{old_path}")
            errors.extend(check_superseded(old_path, old, new, supersedes[old_path]))
        else:
            errors.append(
                f"{old_path}: modified; files under {REGRESSIONS} are append-only "
                "(put new tests in a new file, or name the superseded test on the Issue)"
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
