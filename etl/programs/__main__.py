"""Check catalog links live, without modifying verification dates. No auth/env required."""

import argparse
from pathlib import Path

from etl.programs import load_catalog
from etl.programs.links import check_catalog
from etl.programs.revalidation import load_checks, revalidate, save_checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revalidate", action="store_true", help="preview content hashes and required review"
    )
    parser.add_argument(
        "--checks",
        type=Path,
        default=Path("data/program_checks.json"),
        help="validated reviewed baseline and observations JSON (must already exist)",
    )
    parser.add_argument(
        "--save", action="store_true", help="persist observations, never accept review"
    )
    args = parser.parse_args(argv)
    if args.save and not args.revalidate:
        parser.error("--save requires --revalidate")
    if args.revalidate:
        try:
            state = revalidate(load_catalog(Path("data/programs.yaml")), load_checks(args.checks))
            print(state.model_dump_json(indent=2))
            print("REVIEW required" if state.needs_review else "UNCHANGED reviewed content")
            if args.save:
                save_checks(args.checks, state)
                print(f"Saved observations to {args.checks}; reviewed baseline unchanged.")
            else:
                print("Preview only; use --save to persist observations.")
        except (OSError, ValueError) as exc:
            print(f"Content check failed: {exc}")
            return 1
        return 1 if state.needs_review else 0
    try:
        report = check_catalog(load_catalog(Path("data/programs.yaml")))
    except (OSError, ValueError) as exc:
        print(f"Catalog check failed: {exc}")
        return 1
    for link in report.blocked:
        print(f"BLOCKED {link}")
    for failure in report.failures:
        print(f"FAIL {failure}")
    if not report.failures:
        print(f"No failed links or stale dates; {len(report.blocked)} blocked link(s) unverified.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
