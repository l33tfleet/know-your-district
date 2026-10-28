"""Isolated B22003 outreach facts; mirrors etl/build.py's schema and artifact format.

Build: uv run python -m etl.outreach [--dry-run] (optional CENSUS_API_KEY).
Replay: --source data/outreach/facts/source.json. Verify offline: --check.
Rollback: replay a retained source.json into --output; brief artifacts never change.
Fetch/validation errors leave the previous artifacts intact.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from app.facts import FactStore
from app.models import Fact
from etl.build import check as check_facts
from etl.census import CensusBatch, CensusClient, load_config
from etl.facts import HOUSE, SENATE, facts_from_batch
from etl.indicators import Indicator

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/outreach/facts"
INDICATOR = Indicator(("B22003_006E",), "detailed")
REQUESTS = ("state:15", HOUSE + ":*", SENATE + ":*")
ARTIFACTS = ("facts.db", "facts.tsv", "facts.sha256", "source.json", "provenance.json")


class Source(BaseModel):
    retrieved_at: datetime
    batches: dict[str, CensusBatch]


def _facts(source: Source) -> list[Fact]:
    config = load_config(ROOT / "config.toml")
    if set(source.batches) != set(REQUESTS):
        raise ValueError("Incomplete outreach geography requests")
    facts: list[Fact] = []
    for request in REQUESTS:
        batch = source.batches[request]
        if (
            batch.endpoint != config.base_url.format(year=config.year)
            or batch.vintage != config.vintage
            or batch.labels != {v: config.labels[v] for v in INDICATOR.variables}
        ):
            raise ValueError("Outreach metadata differs from pinned Census configuration")
        facts.extend(facts_from_batch(INDICATOR, batch, request))
    return sorted(facts, key=lambda f: (f.variable, f.geography, f.vintage))


def _provenance(source_bytes: bytes) -> bytes:
    source = Source.model_validate_json(source_bytes)
    return (
        json.dumps(
            {
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "retrieved_at": source.retrieved_at.isoformat(),
                "table_id": "B22003",
                "estimate": "B22003_006E",
                "moe": "B22003_006M",
                "district_plan": 2022,
                "terms": "U.S. public domain; U.S. Census Bureau ACS 5-year",
                "meaning": "Households below poverty that did not receive SNAP; not eligibility",
                "caveat": "Survey benefit receipt is undercounted; national poverty thresholds apply.",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def check(output: Path = OUTPUT) -> bool:
    if not check_facts(output):
        raise ValueError("Missing outreach facts")
    source_bytes = (output / "source.json").read_bytes()
    # Check the digest before parsing so damaged source files have a clear error.
    provenance = json.loads((output / "provenance.json").read_bytes())
    if provenance.get("source_sha256") != hashlib.sha256(source_bytes).hexdigest():
        raise ValueError("Outreach provenance source digest differs")
    if _provenance(source_bytes) != (output / "provenance.json").read_bytes():
        raise ValueError("Outreach provenance differs")
    facts = _facts(Source.model_validate_json(source_bytes))
    stored = FactStore(output / "facts.db").get(
        [(f.variable, f.geography) for f in facts], facts[0].vintage
    )
    with closing(
        sqlite3.connect((output / "facts.db").resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        count = db.execute("SELECT count(*) FROM facts").fetchone()[0]
    if count != len(facts) or stored != {(f.variable, f.geography): f for f in facts}:
        raise ValueError("Outreach facts differ from source")
    return True


def build(output: Path = OUTPUT, *, source: Path | None = None) -> int:
    if source is None:
        client = CensusClient(
            load_config(ROOT / "config.toml"), api_key=os.environ.get("CENSUS_API_KEY")
        )
        batches = {g: asdict(client.fetch(INDICATOR, g)) for g in REQUESTS}
        source_bytes = (
            json.dumps(
                {"retrieved_at": datetime.now(UTC).isoformat(), "batches": batches},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode()
    else:
        source_bytes = source.read_bytes()
    facts = _facts(Source.model_validate_json(source_bytes))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".outreach-", dir=output) as temporary:
        staged = Path(temporary)
        with closing(sqlite3.connect(staged / "facts.db")) as db:
            db.executescript((ROOT / "data/schema.sql").read_text())
            for fact in facts:
                values = fact.model_dump()
                db.execute(
                    f"INSERT INTO facts ({', '.join(values)}) VALUES "
                    f"({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
            db.commit()

        def cell(value: object) -> str:
            return (
                ""
                if value is None
                else str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
            )

        lines = ["\t".join(Fact.model_fields)]
        lines.extend("\t".join(cell(v) for v in f.model_dump().values()) for f in facts)
        (staged / "facts.tsv").write_text("\n".join(lines) + "\n")
        (staged / "facts.sha256").write_text(
            "".join(
                f"{hashlib.sha256((staged / n).read_bytes()).hexdigest()}  {n}\n"
                for n in ARTIFACTS[:2]
            )
        )
        (staged / "source.json").write_bytes(source_bytes)
        (staged / "provenance.json").write_bytes(_provenance(source_bytes))
        check(staged)
        for name in ARTIFACTS:
            (staged / name).replace(output / name)
    return len(facts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.check:
        check(args.output)
    elif args.dry_run:
        with tempfile.TemporaryDirectory() as temporary:
            print(f"Validated {build(Path(temporary), source=args.source)} outreach facts")
    else:
        print(f"Published {build(args.output, source=args.source)} outreach facts")


if __name__ == "__main__":
    main()
