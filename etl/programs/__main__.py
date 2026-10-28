"""Check catalog links live, without modifying verification dates. No auth/env required."""

import argparse
from pathlib import Path

from etl.programs import load_catalog
from etl.programs.links import check_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        failures = check_catalog(load_catalog(Path("data/programs.yaml")))
    except (OSError, ValueError) as exc:
        print(f"Catalog check failed: {exc}")
        return 1
    for failure in failures:
        print(f"FAIL {failure}")
    if not failures:
        print("All program URLs return 200 on trusted hosts; verification ages are 0–29 days.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
