"""Generate a complete independent ACS sample; publish only after validation.

Run with ``make golden`` or ``uv run python -m scripts.generate_golden``.
The manifest selects geographies, never values or reliability labels. No app,
ETL, fact database or production reliability helpers participate in this oracle.
Observations are deliberately generated separately from their later commit.
"""

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from scripts import independent_oracle as oracle

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COUNTS = {
    "state legislative district (lower chamber)": 4,
    "state legislative district (upper chamber)": 3,
    "county": 4,
    "state": 1,
}
FLAGS = {"reliable", "moderate: use with care", "use with caution"}


class Selection(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    geography: str
    code: str


def read_manifest(path: Path) -> list[Selection]:
    selections = TypeAdapter(list[Selection]).validate_json(path.read_bytes())
    keys = [oracle.geography_key(item.geography, item.code) for item in selections]
    if Counter(item.geography for item in selections) != REQUIRED_COUNTS or len(set(keys)) != 12:
        raise oracle.OracleError(
            "Sample requires four House, three Senate, four counties and state"
        )
    return selections


def reliability(value: float | None, moe: float | None) -> tuple[float | None, str]:
    """Independently apply the published 90% MOE/CV contract from docs/data.md."""
    if value is None or value == 0 or moe is None:
        return None, "use with caution"
    if not math.isfinite(value) or not math.isfinite(moe) or value < 0 or moe < 0:
        raise oracle.OracleError("Invalid observation for CV")
    cv = (moe / 1.645) / value
    if not math.isfinite(cv):
        raise oracle.OracleError("Invalid observation CV")
    return cv, (
        "reliable"
        if cv <= 0.15
        else "moderate: use with care"
        if cv <= 0.30
        else "use with caution"
    )


def generate(selections: list[Selection]) -> str:
    cases: list[dict[str, object]] = []
    coverage: set[str] = set()
    keys: set[tuple[str, str, str]] = set()
    for item in selections:
        geography = oracle.geography_key(item.geography, item.code)
        for variable in sorted(oracle.LABELS):
            observation = oracle.fetch(variable, item.geography, item.code)
            if (
                observation.variable != variable
                or observation.geography != geography
                or observation.vintage != "2020–2024"
                or observation.label != oracle.LABELS[variable]
            ):
                raise oracle.OracleError("Observation identity or label mismatch")
            key = (observation.variable, observation.geography, observation.vintage)
            if key in keys:
                raise oracle.OracleError("Duplicate golden join key")
            keys.add(key)
            cv, flag = reliability(observation.value, observation.moe)
            # Missing/controlled cells remain in the artifact but do not prove
            # numeric caution coverage. Coverage must come from fetched values.
            if cv is not None:
                coverage.add(flag)
            case: dict[str, object] = asdict(observation)
            case.update(cv=cv, reliability=flag)
            cases.append(case)
    if len(cases) != 300 or coverage != FLAGS:
        raise oracle.OracleError(
            "Sample must have 300 cells and reliable, moderate and caution CV coverage"
        )
    cases.sort(
        key=lambda case: (str(case["variable"]), str(case["geography"]), str(case["vintage"]))
    )
    return json.dumps(cases, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"


def publish(output: Path, content: str) -> None:
    """A same-directory rename leaves an existing artifact intact on failure."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "scripts/golden_sample.json")
    parser.add_argument("--output", type=Path, default=ROOT / "tests/golden/acs_2024.json")
    args = parser.parse_args(argv)
    try:
        content = generate(read_manifest(args.manifest))
        publish(args.output, content)
    except (oracle.OracleError, OSError, ValueError, ValidationError) as error:
        # Never print request URLs, response bodies, credentials or local OS errors.
        message = (
            str(error) if isinstance(error, oracle.OracleError) else "Invalid manifest or output"
        )
        print(message, file=sys.stderr)
        return 1
    print("Generated 300 complete cases; reliable, moderate and caution CV coverage verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
