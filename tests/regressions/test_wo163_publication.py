"""The production publication reproduces an authentic Census summary capture."""

import csv
import io
import json
import sqlite3
from pathlib import Path


def test_publication_matches_captured_census_summary() -> None:
    root = Path(__file__).resolve().parents[2] / "data/outreach/facts"
    source = json.loads((root / "source.json").read_text())
    acquisition = source["acquisition"]
    assert acquisition["url"] == (
        "https://www2.census.gov/programs-surveys/acs/summary_file/2024/"
        "table-based-SF/data/5YRData/acsdt5y2024-b22003.dat"
    )
    assert len(acquisition["sha256"]) == 64
    assert (
        acquisition["metadata"]["label"] == source["batches"]["state:15"]["labels"]["B22003_006E"]
    )
    # Read the retained summary lines independently of CensusBatch/facts_from_batch.
    expected: dict[str, tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO(acquisition["selected_rows"]), delimiter="|"):
        geo = row["GEO_ID"]
        if geo == "0400000US15":
            key = "state:15"
        else:
            assert geo.startswith(("620L900US15", "610U900US15"))
            chamber = "house" if geo.startswith("620") else "senate"
            key = f"{chamber}:15:{geo[-3:]}:2022"
        assert key not in expected
        expected[key] = (float(row["B22003_E006"]), float(row["B22003_M006"]))
    assert set(expected) == (
        {"state:15"}
        | {f"house:15:{n:03}:2022" for n in range(1, 52)}
        | {f"senate:15:{n:03}:2022" for n in range(1, 26)}
    )
    with sqlite3.connect((root / "facts.db").as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT geography, value, moe FROM facts").fetchall()
    assert len(rows) == len(expected)
    assert {geo: (value, moe) for geo, value, moe in rows} == expected
