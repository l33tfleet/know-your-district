"""#206: publish the operator's complete population refresh, verified offline.

Operator: b0106ed, `uv run python -m etl.build --populations`, retrieved
2026-10-29 19:17 UTC from https://api.census.gov/data/2024/acs/acs5.
No credentials or operator-local files are needed to run these checks.
"""

import csv
import hashlib
from pathlib import Path

import pytest

from app.analysis.populations import compare
from app.facts import FactStore
from app.models import Fact
from app.populations import load_populations
from etl.build import check
from etl.population_variables import load_population_config

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/populations"
REGISTRY = load_populations()
CELLS = {c for p in REGISTRY.populations for c in p.numerator + p.denominator}
GEOGRAPHIES = (
    "state:15",
    *(f"county:15:{code}" for code in ("001", "003", "007", "009")),
    *(f"house:15:{i:03}:2022" for i in range(1, 52)),
    *(f"senate:15:{i:03}:2022" for i in range(1, 26)),
)


@pytest.fixture(scope="module")
def facts() -> dict[tuple[str, str], Fact]:
    return FactStore(OUTPUT / "facts.db").get(
        ((cell, geography) for cell in CELLS for geography in GEOGRAPHIES), REGISTRY.vintage
    )


def test_every_registry_cell_covers_all_81_geographies(facts: dict[tuple[str, str], Fact]) -> None:
    assert len(GEOGRAPHIES) == 81
    assert set(facts) == {(cell, geography) for cell in CELLS for geography in GEOGRAPHIES}
    config = load_population_config(ROOT / "config.toml")
    for (cell, geography), fact in facts.items():
        assert fact.geography == geography
        assert fact.vintage == REGISTRY.vintage
        assert fact.source == REGISTRY.source
        assert fact.table_id == cell.split("_")[0]
        assert fact.label == config.labels[cell]
        endpoint = "profile" if cell.startswith("DP") else "subject" if cell.startswith("S") else ""
        assert fact.endpoint == "https://api.census.gov/data/2024/acs/acs5" + (
            f"/{endpoint}" if endpoint else ""
        )
        assert fact.method.startswith(REGISTRY.method)
        if fact.value is None:
            assert fact.reliability == "unavailable"
            assert "not available" in fact.method or fact.estimate_annotation
        if fact.moe is None:
            assert fact.cv is None
            assert "MOE controlled" in fact.method or "MOE not available" in fact.method


def test_published_bytes_match_the_operator_refresh() -> None:
    expected = {
        "facts.db": "21bdcd7d43c975266fc2216855547930d3daf3fab7ef8763889f2b3429a5e8d9",
        "facts.tsv": "665fc0eff021859a41ff7f7d63cffbea5562f5ecf021f9a24f42a7b7389fda02",
        "facts.sha256": "b6801df629cdf6b9452c780877f073cc7de38cdb384f35db273354c51c55c4d7",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest() == digest
    # Also validates every row, exact schema, canonical TSV, and the digest manifest.
    assert check(OUTPUT)


def test_population_comparisons_use_the_registry_definitions(
    facts: dict[tuple[str, str], Fact],
) -> None:
    assert facts, "The real population artifacts must be published"
    for population in REGISTRY.populations:
        results = compare(population, GEOGRAPHIES, facts)
        assert tuple(r.geography for r in results) == GEOGRAPHIES
        for result in results:
            assert result.count.numerator == population.numerator
            assert result.share.numerator == population.numerator
            assert result.share.denominator == population.denominator
            assert result.share.universe == population.universe
            assert not result.count.missing
            assert not result.share.missing
            assert result.count.value is not None
            assert result.share.value is not None
            assert 0 <= result.share.value <= 100
            assert {(f.variable, f.geography) for f in result.share.inputs} == {
                (cell, result.geography) for cell in population.numerator + population.denominator
            }


def test_snap_cells_agree_with_independent_census_bulk_source(
    facts: dict[tuple[str, str], Fact],
) -> None:
    # The retained official bulk-table excerpt is independent of the API refresh.
    with (ROOT / "data/snap/evidence/b22003-hawaii.dat").open() as stream:
        rows = {row["GEO_ID"]: row for row in csv.DictReader(stream, delimiter="|")}
    for geography in GEOGRAPHIES:
        parts = geography.split(":")
        prefix = {
            "state": "0400000US",
            "county": "0500000US",
            "house": "620L900US",
            "senate": "610U900US",
        }[parts[0]]
        source = rows[prefix + "".join(parts[1:3])]
        for cell in ("003", "006"):
            fact = facts[(f"B22003_{cell}E", geography)]
            assert fact.value == float(source[f"B22003_E{cell}"])
            assert fact.moe == float(source[f"B22003_M{cell}"])
