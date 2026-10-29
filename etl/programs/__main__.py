"""Check catalog links live, without modifying verification dates. No auth/env required."""

import argparse
from pathlib import Path

from etl.programs import load_catalog
from etl.programs.links import check_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
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
