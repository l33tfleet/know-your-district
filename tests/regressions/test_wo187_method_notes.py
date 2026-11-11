"""WO187: stored method notes end each clause as a sentence, keeping every word.

Replaces test_wo116_sentinel_status.py::test_sentinel_method_text and
::test_missing_and_real_cells_keep_method_and_annotation_order, which pinned the
old semicolon separators. Every sentinel code, decimal form, position,
annotation, value, MOE, CV and reliability check is kept; only the separator
between clauses changed from "; " to ". ".
"""

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

import pytest

from app.models import Fact
from etl.build import check
from etl.census import CensusBatch
from etl.facts import METHOD_SEPARATOR, facts_from_batch
from etl.indicators import INDICATORS
from scripts.readability_corpus import check_reading

ROOT = Path(__file__).resolve().parents[2]
BASE = "published estimate and 90% margin of error"
CONTROLLED = "published estimate and 90% margin of error. MOE controlled. MOE annotation: *****"


def _fact(estimate: str | None, moe: str | None) -> Fact:
    group = INDICATORS["median_gross_rent"]
    batch = CensusBatch(
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        vintage="2020–2024",
        labels={"B25064_001E": "Estimate!!Median gross rent"},
        rows=[
            {
                "state": "15",
                "B25064_001E": estimate,
                "B25064_001M": moe,
                "B25064_001EA": "estimate note",
                "B25064_001MA": "MOE note",
            }
        ],
    )
    return facts_from_batch(group, batch, "state:15")[0]


def test_separator_is_a_sentence_boundary() -> None:
    assert METHOD_SEPARATOR == ". "


@pytest.mark.parametrize(
    "code,status",
    [
        ("-666666666", "not available"),
        ("-999999999", "not available"),
        ("-888888888", "not available"),
        ("-555555555", "controlled"),
        ("-222222222", "not available"),
        ("-333333333", "not available: median in open-ended interval (top/bottom-coded)"),
    ],
)
@pytest.mark.parametrize("suffix", ["", ".0"])
@pytest.mark.parametrize("position", ["estimate", "MOE"])
def test_sentinel_method_sentences(code: str, status: str, suffix: str, position: str) -> None:
    raw = code + suffix
    fact = _fact(raw, "10") if position == "estimate" else _fact("100", raw)
    estimate_clause = f". estimate {status}" if position == "estimate" else ""
    moe_clause = f". MOE {status}" if position == "MOE" else ""
    assert fact.method == (
        "published estimate and 90% margin of error"
        f"{estimate_clause}. estimate annotation: estimate note"
        f"{moe_clause}. MOE annotation: MOE note"
    )
    assert "; " not in fact.method
    assert fact.value == (None if position == "estimate" else 100)
    assert fact.moe == (10 if position == "estimate" else None)
    assert fact.cv is None
    assert fact.reliability == ("unavailable" if position == "estimate" else "caution")


@pytest.mark.parametrize("position", ["estimate", "MOE", "both", "neither"])
def test_missing_and_real_cells_keep_method_sentences_in_order(position: str) -> None:
    estimate_missing = position in ("estimate", "both")
    moe_missing = position in ("MOE", "both")
    fact = _fact(None if estimate_missing else "100", None if moe_missing else "10")
    estimate_clause = ". estimate not available" if estimate_missing else ""
    moe_clause = ". MOE not available" if moe_missing else ""
    assert fact.method == (
        "published estimate and 90% margin of error"
        f"{estimate_clause}. estimate annotation: estimate note"
        f"{moe_clause}. MOE annotation: MOE note"
    )
    assert fact.value == (None if estimate_missing else 100)
    assert fact.moe == (None if moe_missing else 10)


def test_no_annotation_and_no_status_keeps_the_bare_method() -> None:
    group = INDICATORS["median_gross_rent"]
    batch = CensusBatch(
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        vintage="2020–2024",
        labels={"B25064_001E": "Estimate!!Median gross rent"},
        rows=[
            {
                "state": "15",
                "B25064_001E": "100",
                "B25064_001M": "10",
                "B25064_001EA": None,
                "B25064_001MA": None,
            }
        ],
    )
    fact = facts_from_batch(group, batch, "state:15")[0]
    assert fact.method == BASE
    assert (fact.value, fact.moe, fact.reliability) == (100, 10, "reliable")


def _non_method_digest(tsv: Path) -> str:
    lines = tsv.read_text(encoding="utf-8").splitlines()
    method = lines[0].split("\t").index("method")
    body = ["\t".join(c for i, c in enumerate(row.split("\t")) if i != method) for row in lines]
    return hashlib.sha256("\n".join(body).encode()).hexdigest()


# Digests of every TSV field except method, taken from origin/main before #187.
# A change to any value, MOE, CV, reliability, source, table, vintage, geography,
# endpoint, label or annotation fails here.
UNCHANGED = {
    "data": ("fb8e304db91535b78cf9268684fcbb3d47d8c4e1023fa929d5c2d73c0808d322", 243, 6),
    "data/populations": (
        "520b47eae0f46fe5e3314acb12be8824439b7b9d63533fe43913e2dc4d9f041c",
        5670,
        7,
    ),
}


@pytest.mark.parametrize("folder", sorted(UNCHANGED))
def test_rebuilt_artifacts_change_only_method_separators(folder: str) -> None:
    output = ROOT / folder
    digest, rows, controlled = UNCHANGED[folder]
    assert check(output)  # TSV equals the database export; digests match both files
    assert _non_method_digest(output / "facts.tsv") == digest
    with closing(
        sqlite3.connect((output / "facts.db").resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        methods = Counter(m for (m,) in db.execute("SELECT method FROM facts"))
    assert methods == Counter({BASE: rows - controlled, CONTROLLED: controlled})
    for method in methods:
        assert "; " not in method
        reading = check_reading(method)
        assert reading.ok, (method, reading)
