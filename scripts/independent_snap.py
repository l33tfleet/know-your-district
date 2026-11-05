"""Independent B22003 district oracle and offline SNAP artifact gate.

``python -m scripts.independent_snap --fetch`` prints a fresh House 1 oracle
from the official public bulk table without importing the app, ETL or config.
Redirect to a temporary file and review before replacing the golden fixture.
No environment variables or credentials. Default: offline validation.
``--build-summary --dry-run`` previews a rebuild from the committed source
excerpt; ``--build-summary`` publishes. Removing data/snap rolls back these
isolated artifacts; core facts are untouched.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import UTC, date, datetime
from http.client import HTTPException
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.census.gov/data/2024/acs/acs5"
VARIABLE = "B22003_006E"
LABEL = (
    "Estimate!!Total:!!Household did not receive Food Stamps/SNAP in the past 12 months:"
    "!!Income in the past 12 months below poverty level"
)
SUMMARY_URL = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2024/"
    "table-based-SF/data/5YRData/acsdt5y2024-b22003.dat"
)
METADATA_URL = f"{BASE}/variables/{VARIABLE}.json"
HEADER = ["GEO_ID"] + [f"B22003_{kind}{cell:03}" for cell in range(1, 8) for kind in ("E", "M")]
GOLDEN = ROOT / "tests/regressions/fixtures/wo136_snap.json"
EVIDENCE_URLS = {
    "evidence/dhs-snap.html": "https://humanservices.hawaii.gov/bessd/snap/",
    "evidence/dhs-outreach.html": "https://humanservices.hawaii.gov/bessd/snap-outreach-providers/",
    "evidence/auw211.html": "https://auw211.org/",
    "evidence/census-metadata.json": METADATA_URL,
    "evidence/b22003-hawaii.dat": SUMMARY_URL,
    "provenance.json": SUMMARY_URL,
    "referrals.json": "https://humanservices.hawaii.gov/bessd/snap/",
}


class Metadata(BaseModel):
    label: str
    attributes: str


class Golden(BaseModel):
    retrieved_on: date
    metadata_url: str
    source_url: str
    full_source_sha256: str
    metadata: Metadata
    header: list[str]
    row: list[str]


class Evidence(BaseModel):
    retrieved_on: date
    source_url: str
    sha256: str


def request(url: str) -> bytes:
    """Contain Census transport failures and report latency without response bodies."""
    started = perf_counter()
    try:
        with urlopen(url, timeout=30) as response:
            return response.read()
    except (OSError, HTTPException):
        raise ValueError("Independent Census request failed") from None
    finally:
        print(f"Independent Census request: {perf_counter() - started:.3f}s", file=sys.stderr)


def golden_values(golden: Golden) -> tuple[float, float]:
    if (
        golden.source_url != SUMMARY_URL
        or golden.metadata_url != METADATA_URL
        or golden.metadata.label != LABEL
        or not {"B22003_006M", "B22003_006EA", "B22003_006MA"}
        <= set(golden.metadata.attributes.split(","))
    ):
        raise ValueError("Independent golden metadata/request mismatch")
    if golden.header != HEADER or len(golden.row) != 15 or golden.row[0] != "620L900US15001":
        raise ValueError("Independent golden response mismatch")
    # Independent fixed-column reading of the original published line, not ETL output.
    estimate, moe = float(golden.row[11]), float(golden.row[12])
    if not all(math.isfinite(value) and value >= 0 for value in (estimate, moe)):
        raise ValueError("Independent golden numeric cell unavailable")
    return estimate, moe


def fetch() -> Golden:
    """Download the public table; no production imports or Census API key needed."""
    metadata = json.loads(request(METADATA_URL))
    payload = request(SUMMARY_URL)
    lines = csv.reader(io.StringIO(payload.decode("utf-8-sig")), delimiter="|")
    try:
        header = next(lines)
        row = next(row for row in lines if row[0] == "620L900US15001")
    except StopIteration:
        raise ValueError("Independent summary missing House district 1") from None
    golden = Golden.model_validate(
        {
            "retrieved_on": datetime.now(UTC).date(),
            "metadata_url": METADATA_URL,
            "source_url": SUMMARY_URL,
            "full_source_sha256": hashlib.sha256(payload).hexdigest(),
            "metadata": metadata,
            "header": header,
            "row": row,
        }
    )
    golden_values(golden)
    return golden


def validate_facts(database: Path, golden_path: Path) -> None:
    golden = Golden.model_validate_json(golden_path.read_bytes())
    estimate, moe = golden_values(golden)
    expected = {"state:15"} | {f"county:15:{code}" for code in ("001", "003", "007", "009")}
    expected |= {
        f"{chamber}:15:{number:03}:2022"
        for chamber, count in (("house", 51), ("senate", 25))
        for number in range(1, count + 1)
    }
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT geography, variable, vintage, table_id, endpoint, label, value, moe, source, method FROM facts"
        ).fetchall()
    if len(rows) != 81 or {row[0] for row in rows} != expected:
        raise ValueError("SNAP geography set must be exactly 76 districts, four counties and state")
    expected_method = (
        "published estimate and 90% margin of error; bulk table "
        + SUMMARY_URL
        + "; annotation columns not supplied by summary file"
    )
    if any(
        row[1:6] != (VARIABLE, "2020–2024", "B22003", BASE, LABEL)
        or row[8:] != ("U.S. Census Bureau ACS 5-year", expected_method)
        for row in rows
    ):
        raise ValueError("SNAP cell provenance mismatch")
    district = next(row for row in rows if row[0] == "house:15:001:2022")
    if district[6:8] != (estimate, moe):
        raise ValueError("SNAP independent golden estimate/MOE mismatch")


def build_summary(output: Path, *, dry_run: bool) -> None:
    """Replay unchanged Census lines through the production fact converter.

    This builder is deliberately separate from the oracle's fixed-column reader.
    The bulk source has no annotation columns; the method records that limitation.
    All files are staged and validated before publishing; core data is untouched.
    """
    from app.models import Fact
    from etl.build import ARTIFACTS, check
    from etl.census import CensusBatch, CensusError
    from etl.facts import HOUSE, SENATE, facts_from_batch
    from etl.indicators import Indicator

    metadata = Metadata.model_validate_json((output / "evidence/census-metadata.json").read_bytes())
    if metadata.label != LABEL:
        raise ValueError("Summary metadata label mismatch")
    with (output / "evidence/b22003-hawaii.dat").open() as stream:
        reader = csv.DictReader(stream, delimiter="|")
        if reader.fieldnames != HEADER:
            raise ValueError("Summary header mismatch")
        source_rows = list(reader)
    facts: list[Fact] = []
    for geography, prefix, column in (
        ("state:15", "0400000US", "state"),
        ("county:*", "0500000US15", "county"),
        (HOUSE + ":*", "620L900US15", HOUSE),
        (SENATE + ":*", "610U900US15", SENATE),
    ):
        rows = [
            {
                VARIABLE: row["B22003_E006"],
                "B22003_006M": row["B22003_M006"],
                "B22003_006EA": None,
                "B22003_006MA": None,
                "state": "15",
                column: row["GEO_ID"][len(prefix) :],
            }
            for row in source_rows
            if row["GEO_ID"].startswith(prefix)
        ]
        batch = CensusBatch(BASE, "2020–2024", {VARIABLE: LABEL}, rows)
        try:
            facts.extend(facts_from_batch(Indicator((VARIABLE,), "detailed"), batch, geography))
        except CensusError as error:
            raise ValueError(str(error)) from None
    facts = [
        fact.model_copy(
            update={
                "method": fact.method
                + "; bulk table "
                + SUMMARY_URL
                + "; annotation columns not supplied by summary file"
            }
        )
        for fact in facts
    ]
    facts.sort(key=lambda fact: (fact.variable, fact.geography, fact.vintage))
    with tempfile.TemporaryDirectory(
        prefix=".snap-summary-", dir=None if dry_run else output
    ) as temporary:
        staged = Path(temporary)
        with closing(sqlite3.connect(staged / "facts.db")) as db:
            db.executescript((ROOT / "data/schema.sql").read_text())
            columns = list(Fact.model_fields)
            for fact in facts:
                db.execute(
                    f"INSERT INTO facts ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(fact.model_dump().values()),
                )
            db.commit()
            # Mirrors the canonical encoding in etl/build.py; check() verifies the bytes.
            lines = ["\t".join(columns)]
            for row in db.execute("SELECT * FROM facts ORDER BY variable, geography, vintage"):
                lines.append(
                    "\t".join(
                        ""
                        if value is None
                        else str(value)
                        .replace("\\", "\\\\")
                        .replace("\t", "\\t")
                        .replace("\n", "\\n")
                        for value in row
                    )
                )
        (staged / "facts.tsv").write_text("\n".join(lines) + "\n")
        (staged / "facts.sha256").write_text(
            "".join(
                f"{hashlib.sha256((staged / name).read_bytes()).hexdigest()}  {name}\n"
                for name in ARTIFACTS[:2]
            )
        )
        check(staged)
        validate_facts(staged / "facts.db", GOLDEN)
        if not dry_run:
            for name in ARTIFACTS:
                (staged / name).replace(output / name)
    print(
        f"SNAP summary replay: {len(facts)} facts; " + ("preview only" if dry_run else "published")
    )


def validate_artifacts(output: Path, golden_path: Path = GOLDEN) -> None:
    # Shared canonical byte/schema check follows the independent cell and coverage checks.
    from etl.build import check

    required = (
        "facts.db",
        "facts.tsv",
        "facts.sha256",
        "evidence.json",
        "provenance.json",
        "referrals.json",
    )
    if not all((output / name).is_file() for name in required):
        raise ValueError("Missing SNAP artifacts")
    validate_facts(output / "facts.db", golden_path)
    check(output)
    manifest = json.loads((output / "evidence.json").read_bytes())
    for name, url in EVIDENCE_URLS.items():
        evidence = Evidence.model_validate(manifest[name])
        if evidence.source_url != url:
            raise ValueError("Evidence source URL mismatch")
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != evidence.sha256:
            raise ValueError("Evidence digest mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fetch", action="store_true", help="print independent golden JSON")
    modes.add_argument(
        "--build-summary", action="store_true", help="replay the published source excerpt"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="validate a rebuild without publishing"
    )
    args = parser.parse_args()
    if args.dry_run and not args.build_summary:
        parser.error("--dry-run requires --build-summary")
    try:
        if args.fetch:
            print(fetch().model_dump_json(indent=2))
        elif args.build_summary:
            build_summary(ROOT / "data/snap", dry_run=args.dry_run)
        else:
            validate_artifacts(ROOT / "data/snap")
            print(
                "SNAP artifacts: exact coverage, independent golden, canonical bytes and evidence OK"
            )
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(f"SNAP validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
