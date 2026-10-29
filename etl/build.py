"""Build and verify the published fact artifacts.

``make data`` reads CENSUS_API_KEY (optional); ``make check`` verifies offline.
Only facts.db, facts.tsv and facts.sha256 are published. Failed fetches or
validation leave the previous set intact. Rebuild all three to roll back a
format/schema change; never edit the TSV or digest manifest by hand.

The default build keeps the legacy indicators in data/. ``--populations`` refreshes
the registry cells (data/populations.yaml) into data/populations/ with the same
schema and file names. No build publishes a set missing a variable already
published there: delete the artifacts deliberately to drop one.
"""

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Literal

from app.models import Fact
from app.populations import PopulationRegistry, load_populations
from etl.census import CensusClient, CensusError, load_config
from etl.facts import HOUSE, SENATE, facts_from_batch
from etl.indicators import BUILD_INDICATORS, INDICATORS, Indicator
from etl.population_variables import load_population_config

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ("facts.db", "facts.tsv", "facts.sha256")
POPULATION_OUTPUT = ROOT / "data/populations"
_ENDPOINTS: dict[str, Literal["profile", "subject"]] = {"DP": "profile", "S1": "subject"}


def population_indicators(registry: PopulationRegistry | None = None) -> tuple[Indicator, ...]:
    """Every registry cell, one published table per request, at most 12 cells (48 columns)."""
    populations = (registry or load_populations()).populations
    tables: dict[str, list[str]] = {}
    for cell in sorted({c for p in populations for c in p.numerator + p.denominator}):
        tables.setdefault(cell.split("_")[0], []).append(cell)
    return tuple(
        Indicator(tuple(cells[i : i + 12]), _ENDPOINTS.get(table[:2], "detailed"))
        for table, cells in tables.items()
        for i in range(0, len(cells), 12)
    )


def _published_variables(database: Path) -> set[str]:
    if not database.exists():
        return set()
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return {row[0] for row in db.execute("SELECT DISTINCT variable FROM facts")}


def _schema_objects(db: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return db.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        "WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def _export(database: Path, schema: Path) -> bytes:
    """Validate stored rows against both Fact and the current schema, then encode."""
    with (
        closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db,
        closing(sqlite3.connect(":memory:")) as expected,
    ):
        expected.executescript(schema.read_text(encoding="utf-8"))
        if _schema_objects(db) != _schema_objects(expected):
            raise ValueError("Fact database schema changed: rebuild with make data")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Fact database integrity check failed")
        columns: list[str] = [row[1] for row in expected.execute("PRAGMA table_info(facts)")]
        # Column names come only from the local schema, not request input.
        names = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
        insert = f"INSERT INTO facts ({names}) VALUES ({', '.join('?' for _ in columns)})"
        lines = ["\t".join(columns) + "\n"]
        for row in db.execute("SELECT * FROM facts ORDER BY variable, geography, vintage"):
            Fact.model_validate(dict(zip(columns, row, strict=True)))
            expected.execute(insert, row)
            lines.append("\t".join(_cell(value) for value in row) + "\n")
        return "".join(lines).encode("utf-8")


def _digests(output: Path) -> bytes:
    return "".join(
        f"{hashlib.sha256((output / name).read_bytes()).hexdigest()}  {name}\n"
        for name in ARTIFACTS[:2]
    ).encode("utf-8")


def check(output: Path = ROOT / "data", *, schema: Path = ROOT / "data/schema.sql") -> bool:
    """Check canonical bytes, current schema, and sha256sum-compatible digests."""
    database = output / "facts.db"
    if not database.exists():
        print("no data yet: the data work order builds it")
        return False
    if _export(database, schema) != (output / "facts.tsv").read_bytes():
        raise ValueError("Fact TSV differs from database: rebuild with make data")
    if _digests(output) != (output / "facts.sha256").read_bytes():
        raise ValueError("Fact artifact digests differ: rebuild with make data")
    return True


def build(
    client: CensusClient,
    output: Path = ROOT / "data",
    *,
    schema: Path = ROOT / "data/schema.sql",
    indicators: tuple[Indicator, ...] = tuple(INDICATORS[name] for name in BUILD_INDICATORS),
) -> int:
    """Stage a complete, validated build before replacing any published file."""
    facts: list[Fact] = []
    for indicator in indicators:
        for geography in ("state:15", "county:*", HOUSE + ":*", SENATE + ":*"):
            facts.extend(facts_from_batch(indicator, client.fetch(indicator, geography), geography))
    facts.sort(key=lambda fact: (fact.variable, fact.geography, fact.vintage))
    output.mkdir(parents=True, exist_ok=True)
    # Same filesystem as the destination makes each replacement atomic. Temporary
    # files disappear even when schema validation or export fails.
    with tempfile.TemporaryDirectory(prefix=".facts-", dir=output) as temporary:
        staged = Path(temporary)
        with closing(sqlite3.connect(staged / "facts.db")) as db:
            db.executescript(schema.read_text(encoding="utf-8"))
            for fact in facts:
                values = Fact.model_validate(fact).model_dump()
                db.execute(
                    f"INSERT INTO facts ({', '.join(values)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
            db.commit()
        (staged / "facts.tsv").write_bytes(_export(staged / "facts.db", schema))
        (staged / "facts.sha256").write_bytes(_digests(staged))
        check(staged, schema=schema)
        if removed := _published_variables(output / "facts.db") - {f.variable for f in facts}:
            raise ValueError(
                f"Refresh would remove published facts from {output}: {', '.join(sorted(removed))}"
                "; select them, or delete the artifacts deliberately"
            )
        for name in ARTIFACTS:
            (staged / name).replace(output / name)
    return len(facts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify artifacts offline")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate a build without publishing"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--populations",
        action="store_true",
        help="refresh the registry populations into <output>/populations/",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--config", type=Path, default=ROOT / "config.toml")
    selection.add_argument(
        "--sources", type=Path, help="discover acs.yaml and additional *.yaml source manifests"
    )
    args = parser.parse_args()
    if args.check and args.dry_run:
        parser.error("--check and --dry-run are mutually exclusive")
    if args.populations and args.sources is not None:
        parser.error("--populations and --sources are mutually exclusive")
    try:
        if args.sources is not None:
            from etl.source_build import build_sources, discover_sources

            if args.check:
                for relative, _source in discover_sources(args.sources):
                    check(args.output / relative)
            elif args.dry_run:
                with tempfile.TemporaryDirectory(prefix="sources-preview-") as temporary:
                    count = build_sources(args.sources, Path(temporary))
                print(f"Validated {count} facts; would publish separate source artifacts")
            else:
                count = build_sources(args.sources, args.output)
                print(f"Built {count} facts in {args.output}")
        else:
            output: Path = args.output / "populations" if args.populations else args.output
            if args.check:
                check(output)
                return 0
            if args.populations:
                config = load_population_config(args.config)
                indicators = population_indicators()
            else:
                config = load_config(args.config)
                indicators = tuple(INDICATORS[name] for name in BUILD_INDICATORS)
            client = CensusClient(config, api_key=os.environ.get("CENSUS_API_KEY"))
            if args.dry_run:
                with tempfile.TemporaryDirectory(prefix="facts-preview-") as temporary:
                    count = build(client, Path(temporary), indicators=indicators)
                print(f"Validated {count} facts; would publish {', '.join(ARTIFACTS)} in {output}")
            else:
                count = build(client, output, indicators=indicators)
                print(f"Built {count} facts in {output}")
    except (CensusError, OSError, ValueError, sqlite3.Error) as error:
        print(f"Fact build/check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
