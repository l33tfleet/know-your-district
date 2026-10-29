"""Shared displayed facts and the district-bound agent tool (#180 / #140)."""

import sqlite3
from pathlib import Path

import pytest

from app.tools.facts import DistrictFacts
from etl.boundaries import DistrictId
from tests.regressions.test_wo97_brief_page import VARIABLES, build_db, row

DISTRICT = "house:15:022:2022"
COUNTY = "county:15:003"
STATE = "state:15"


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistrictFacts:
    path = tmp_path / "facts.db"
    build_db(
        path,
        [
            row(indicator, geography, 1234, 12)
            for indicator in VARIABLES
            for geography in (DISTRICT, COUNTY, STATE, "house:15:023:2022", "county:15:009")
        ],
    )
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return DistrictFacts(DistrictId(chamber="house", district=22))


@pytest.mark.parametrize("geography", [DISTRICT, COUNTY, STATE])
def test_get_facts_preserves_published_rows(tool: DistrictFacts, geography: str) -> None:
    assert tool.get_facts(geography, list(VARIABLES)) == {
        indicator: row(indicator, geography, 1234, 12) for indicator in VARIABLES
    }


@pytest.mark.parametrize(
    "geography",
    [
        "house:15:023:2022",
        "senate:15:022:2022",
        "county:15:009",
        "county:15:005",
        "state:06",
        "house:15:022:2012",
        "../state:15",
        "state:15?x",
        "state:15#x",
        "state:%31%35",
        "state:15\n",
    ],
)
def test_get_facts_rejects_outside_display(tool: DistrictFacts, geography: str) -> None:
    with pytest.raises(ValueError, match="geography must be one of"):
        tool.get_facts(geography, ["population"])


@pytest.mark.parametrize(
    "indicator", ["poverty_rate", "B01003_001E", "age_65_count", "population\n"]
)
def test_get_facts_rejects_undisplayed_indicator(tool: DistrictFacts, indicator: str) -> None:
    with pytest.raises(ValueError, match="indicators must be among"):
        tool.get_facts(DISTRICT, ["population", indicator])


def test_missing_row_and_unavailable_value_stay_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "facts.db"
    unavailable = row("age_65_share", DISTRICT, None, None)
    build_db(path, [unavailable])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    tool = DistrictFacts(DistrictId(chamber="house", district=22))
    assert tool.get_facts(DISTRICT, ["population", "age_65_share"]) == {
        "population": None,
        "age_65_share": unavailable,
    }
    assert tool.get_facts(DISTRICT, []) == {}


def test_missing_database_is_not_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "absent.db"
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    tool = DistrictFacts(DistrictId(chamber="senate", district=5))
    assert tool.get_facts(STATE, ["population"]) == {"population": None}
    assert not path.exists()


def test_database_closed_before_tool_result_reaches_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "facts.db"
    build_db(path, [row("population", DISTRICT, 1234, 12)])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def track(database: str, *, uri: bool) -> sqlite3.Connection:
        assert uri and database.endswith("?mode=ro")
        connection = connect(database, uri=uri)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track)
    tool = DistrictFacts(DistrictId(chamber="house", district=22))
    assert tool.get_facts(DISTRICT, ["population"])["population"] is not None
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_tool_includes_every_displayed_county(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.brief_facts as shared

    mapping = shared.load_mapping()
    original = mapping[DISTRICT][0]
    mapping[DISTRICT] = [
        original.model_copy(update={"area_share": 0.75}),
        original.model_copy(update={"county": "county:15:009", "area_share": 0.25}),
    ]
    monkeypatch.setattr(shared, "load_mapping", lambda: mapping)
    path = tmp_path / "split.db"
    rows = [row("population", geography, 1234, 12) for geography in (COUNTY, "county:15:009")]
    build_db(path, rows)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    tool = DistrictFacts(DistrictId(chamber="house", district=22))
    for fact in rows:
        assert tool.get_facts(fact.geography, ["population"]) == {"population": fact}
