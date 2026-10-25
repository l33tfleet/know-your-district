"""Validate a local normalized boundary collection without network or database access."""

import argparse
from pathlib import Path

from pydantic import ValidationError

from etl.boundaries import BoundaryCollection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    path: Path = args.path
    try:
        collection = BoundaryCollection.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        parser.exit(1, f"Boundary validation failed: {exc}\n")
    for feature in collection.features:
        print(feature.properties.key)


if __name__ == "__main__":
    main()
