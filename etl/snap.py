"""Build isolated B22003 joint poverty/nonreceipt facts under data/snap/.

Run ``python -m etl.snap --dry-run`` to validate before publishing, or
``--check`` to verify offline. Reads optional CENSUS_API_KEY. Removing
this directory rolls back the feature; core fact artifacts remain usable.
Referral artifacts are supplied by the later artifact step.
"""

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from etl import build as writer
from etl.census import ACSConfig, CensusClient, CensusError, load_config
from etl.indicators import Indicator

ROOT = Path(__file__).resolve().parents[1]
INDICATOR = Indicator(("B22003_006E",), "detailed")
# Census 2024 B22003_006E metadata; validate through the existing Census facade.
LABEL = (
    "Estimate!!Total:!!Household did not receive Food Stamps/SNAP in the past 12 months:"
    "!!Income in the past 12 months below poverty level"
)


def _output(output: Path | None) -> Path:
    destination = (output if output is not None else ROOT / "data/snap").resolve()
    # Check against the canonical data parent as well: snap itself may be a symlink.
    allowed = (ROOT / "data").resolve() / "snap"
    if not destination.is_relative_to(allowed):
        raise ValueError("SNAP output must be within data/snap/")
    return destination


def build(config: ACSConfig, output: Path | None = None, *, api_key: str | None = None) -> int:
    """Publish the joint cell using the shared validated writer and a private config."""
    destination = _output(output)
    snap_config = config.model_copy(update={"labels": config.labels | {"B22003_006E": LABEL}})
    return writer.build(
        CensusClient(snap_config, api_key=api_key), destination, indicators=(INDICATOR,)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="verify artifacts offline")
    modes.add_argument("--dry-run", action="store_true", help="validate without publishing")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    args = parser.parse_args()
    try:
        output = _output(args.output)
        if args.check:
            writer.check(output)
        else:
            config = load_config(args.config)
            api_key = os.environ.get("CENSUS_API_KEY")
            if args.dry_run:
                with tempfile.TemporaryDirectory(prefix="snap-preview-") as temporary:
                    snap_config = config.model_copy(
                        update={"labels": config.labels | {"B22003_006E": LABEL}}
                    )
                    count = writer.build(
                        CensusClient(snap_config, api_key=api_key),
                        Path(temporary),
                        indicators=(INDICATOR,),
                    )
                print(f"Validated {count} SNAP facts; would publish in {output}")
            else:
                count = build(config, output, api_key=api_key)
                print(f"Built {count} SNAP facts in {output}")
    except (CensusError, OSError, ValueError, sqlite3.Error) as error:
        print(f"SNAP build/check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
