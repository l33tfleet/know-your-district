"""WO147 step 4 (#205): explicit registry-driven population refresh.

The legacy build keeps its defaults; the population refresh writes its own
`data/populations/facts.*`; no refresh silently drops facts already published.
"""

import sqlite3
from pathlib import Path

import pytest

from app.facts import FactStore
from app.populations import load_populations
from etl import build as writer
from etl.census import ACSConfig, CensusBatch, CensusClient, CensusError
from etl.facts import HOUSE
from etl.indicators import BUILD_INDICATORS, INDICATORS, Indicator
from etl.population_variables import load_population_config

ROOT = Path(__file__).resolve().parents[2]
VINTAGE = "2020–2024"


class RecordedClient(CensusClient):
    """Synthetic complete Hawaiʻi geography sets for any requested cells; no HTTP."""

    def __init__(self, *, fail_on: int | None = None) -> None:
        super().__init__(load_population_config(ROOT / "config.toml"))
        self.requests: list[tuple[Indicator, str]] = []
        self.fail_on = fail_on

    def fetch(self, indicator: Indicator, geography: str) -> CensusBatch:
        self.requests.append((indicator, geography))
        if self.fail_on is not None and len(self.requests) == self.fail_on:
            raise CensusError("recorded Census failure")
        if geography == "state:15":
            column, codes = "", ["15"]
        elif geography == "county:*":
            column, codes = "county", ["001", "003", "005", "007", "009"]
        else:
            column = geography[:-2]
            codes = [f"{i:03}" for i in range(1, 52 if column == HOUSE else 26)]
        rows: list[dict[str, str | None]] = []
        for code in codes:
            row: dict[str, str | None] = {"state": "15"}
            if column:
                row[column] = code
            for variable in indicator.variables:
                moe = indicator.moe_variable(variable)
                row |= {variable: "100", moe: "20", variable + "A": None, moe + "A": None}
            rows.append(row)
        labels = {v: f"Label {v}" for v in indicator.variables}
        return CensusBatch(indicator.endpoint, VINTAGE, labels, rows)


def snapshot(path: Path) -> dict[str, bytes]:
    return {name: (path / name).read_bytes() for name in writer.ARTIFACTS}


def variables(path: Path) -> set[str]:
    with sqlite3.connect(path / "facts.db") as db:
        return {row[0] for row in db.execute("SELECT DISTINCT variable FROM facts")}


def registry_cells() -> set[str]:
    registry = load_populations()
    return {c for p in registry.populations for c in p.numerator + p.denominator}


def test_population_indicators_follow_the_registry() -> None:
    indicators = writer.population_indicators()
    cells = [v for indicator in indicators for v in indicator.variables]
    assert sorted(cells) == sorted(registry_cells())
    for indicator in indicators:
        # One published table per request, so each fact cites its own table ID.
        assert {v.split("_")[0] for v in indicator.variables} == {indicator.table_id}
        assert 1 <= len(indicator.variables) <= 12
        expected = {"DP": "profile", "S1": "subject"}.get(indicator.table_id[:2], "detailed")
        assert indicator.endpoint == expected


def test_population_artifacts_live_in_their_own_directory() -> None:
    assert writer.POPULATION_OUTPUT == ROOT / "data/populations"


def test_legacy_default_build_is_unchanged(tmp_path: Path) -> None:
    client = RecordedClient()
    writer.build(client, tmp_path)
    legacy = {v for name in BUILD_INDICATORS for v in INDICATORS[name].variables}
    assert {v for indicator, _ in client.requests for v in indicator.variables} == legacy
    assert variables(tmp_path) == legacy
    assert {p.name for p in tmp_path.iterdir()} == set(writer.ARTIFACTS)


def test_population_refresh_cli_writes_separate_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = RecordedClient()

    def client_factory(config: ACSConfig, *, api_key: str | None = None) -> CensusClient:
        return client

    monkeypatch.setattr(writer, "CensusClient", client_factory)
    monkeypatch.setattr("sys.argv", ["etl.build", "--output", str(tmp_path)])
    assert writer.main() == 0
    shared = snapshot(tmp_path)

    population = tmp_path / "populations"
    argv = ["etl.build", "--populations", "--output", str(tmp_path)]
    monkeypatch.setattr("sys.argv", [*argv, "--dry-run"])
    assert writer.main() == 0
    assert not population.exists()
    monkeypatch.setattr("sys.argv", argv)
    assert writer.main() == 0
    assert snapshot(tmp_path) == shared
    assert {p.name for p in population.iterdir()} == set(writer.ARTIFACTS)
    assert variables(population) == registry_cells()
    monkeypatch.setattr("sys.argv", [*argv, "--check"])
    assert writer.main() == 0

    facts = FactStore(population / "facts.db").get([("B11005_002E", "house:15:022:2022")], VINTAGE)
    fact = facts[("B11005_002E", "house:15:022:2022")]
    assert (fact.value, fact.moe, fact.table_id) == (100.0, 20.0, "B11005")
    assert FactStore(tmp_path / "facts.db").get([("B11005_002E", "state:15")], VINTAGE) == {}


def test_refresh_refuses_to_remove_published_facts(tmp_path: Path) -> None:
    population = tmp_path / "populations"
    writer.build(RecordedClient(), population, indicators=writer.population_indicators())
    before = snapshot(population)
    with pytest.raises(ValueError, match="remove"):
        writer.build(RecordedClient(), population)  # legacy default aimed at the wrong place
    assert snapshot(population) == before
    assert {p.name for p in population.iterdir()} == set(writer.ARTIFACTS)


def test_population_refresh_failure_preserves_artifacts(tmp_path: Path) -> None:
    indicators = writer.population_indicators()
    writer.build(RecordedClient(), tmp_path, indicators=indicators)
    before = snapshot(tmp_path)
    with pytest.raises(CensusError):
        writer.build(
            RecordedClient(fail_on=len(indicators) * 4 - 1), tmp_path, indicators=indicators
        )
    assert snapshot(tmp_path) == before
    assert {p.name for p in tmp_path.iterdir()} == set(writer.ARTIFACTS)
