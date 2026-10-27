"""Offline production coverage, qualified joins and export provenance (WO-77)."""

import json
import re
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

import pytest

from etl.boundaries import BoundaryCollection
from etl.boundaries.production import export_boundaries


def collection() -> dict[str, Any]:
    data = json.loads((Path(__file__).parent / "fixtures/wo47_boundaries.geojson").read_text())
    data["features"] = [
        {**data["features"][0], "properties": {"chamber": chamber, "district": number}}
        for chamber, limit in (("house", 51), ("senate", 25))
        for number in range(1, limit + 1)
    ]
    return data


def database(path: Path, keys: list[str]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE facts (geography TEXT)")
        connection.executemany("INSERT INTO facts VALUES (?)", [(key,) for key in keys])


def keys() -> list[str]:
    return [
        f"{chamber}:15:{number:03}:2022"
        for chamber, limit in (("house", 51), ("senate", 25))
        for number in range(1, limit + 1)
    ]


def test_export_qualified_ids_and_sidecars(tmp_path: Path) -> None:
    db, output = tmp_path / "facts.sqlite", tmp_path / "districts.geojson"
    database(db, [*keys(), *keys(), "state:15", "county:15:001"])
    before = db.read_bytes()
    source = BoundaryCollection.model_validate(collection())
    export_boundaries(source, output, facts_db=db, credit="Synthetic fixture; not official")
    exported = json.loads(output.read_text())
    assert [feature["id"] for feature in exported["features"]] == keys()
    assert exported["features"][0]["geometry"] == source.features[0].geometry.model_dump(
        mode="json"
    )
    assert json.loads(
        output.with_suffix(".provenance.json").read_text()
    ) == source.provenance.model_dump(mode="json")
    assert (
        output.with_suffix(".credit.txt").read_text().strip() == "Synthetic fixture; not official"
    )
    assert db.read_bytes() == before


@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("missing", "boundary key mismatch: missing=['senate:15:025:2022'], extra=[]"),
        ("extra", "district must be in 1..51 for its chamber"),
        ("duplicate", "duplicate district: house-01"),
        ("wrong-chamber", "district must be in 1..25 for its chamber"),
    ],
)
def test_reject_boundary_identity_errors(tmp_path: Path, problem: str, message: str) -> None:
    data = collection()
    if problem == "missing":
        data["features"].pop()
    elif problem == "extra":
        data["features"].append(
            {**data["features"][0], "properties": {"chamber": "house", "district": 52}}
        )
    elif problem == "duplicate":
        data["features"].append(data["features"][0])
    else:
        data["features"][25]["properties"]["chamber"] = "senate"
    output = tmp_path / "districts.geojson"
    if problem == "missing":
        source = BoundaryCollection.model_validate(data)
        with pytest.raises(ValueError, match=re.escape(message)):
            export_boundaries(source, output, credit="Synthetic")
    else:
        with pytest.raises(ValueError, match=re.escape(message)):
            BoundaryCollection.model_validate(data)
    assert not output.exists()


@pytest.mark.parametrize(
    "problem", ["missing", "extra", "wrong-chamber", "wrong-plan", "unqualified"]
)
def test_reject_fact_key_mismatch(tmp_path: Path, problem: str) -> None:
    fact_keys = keys()
    if problem == "missing":
        fact_keys.pop()
    else:
        fact_keys.append(
            {
                "extra": "house:15:052:2022",
                "wrong-chamber": "upper:15:001:2022",
                "wrong-plan": "house:15:001:2012",
                "unqualified": "house-01",
            }[problem]
        )
    db, output = tmp_path / "facts.sqlite", tmp_path / "districts.geojson"
    database(db, fact_keys)
    source = BoundaryCollection.model_validate(collection())
    expected = set(keys())
    message = (
        f"fact key mismatch: missing={sorted(expected - set(fact_keys))}, "
        f"extra={sorted(set(fact_keys) - expected)}"
    )
    with pytest.raises(ValueError, match=re.escape(message)):
        export_boundaries(source, output, facts_db=db, credit="Synthetic")
    assert not output.exists()


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    db = tmp_path / "absent.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        export_boundaries(
            BoundaryCollection.model_validate(collection()),
            tmp_path / "out.geojson",
            facts_db=db,
            credit="Synthetic",
        )
    assert not db.exists()


def test_fact_comparison_connection_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "facts.sqlite"
    database(db, keys())
    connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def checked_connect(database: str, *, uri: bool) -> sqlite3.Connection:
        connection = connect(database, uri=uri)
        connections.append(connection)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO facts VALUES ('unexpected')")
        return connection

    monkeypatch.setattr(sqlite3, "connect", checked_connect)
    export_boundaries(
        BoundaryCollection.model_validate(collection()),
        tmp_path / "out.geojson",
        facts_db=db,
        credit="Synthetic",
    )
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


def test_gis_dependencies_declared() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    assert any(item.startswith("pyshp>=") for item in dependencies)
    assert any(item.startswith("pyproj>=") for item in dependencies)


def test_blank_credit_rejected_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source credit must not be blank"):
        export_boundaries(
            BoundaryCollection.model_validate(collection()),
            tmp_path / "out.geojson",
            credit=" \n",
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("suffix", [".provenance.json", ".credit.txt"])
def test_colliding_sidecar_rejected(tmp_path: Path, suffix: str) -> None:
    output = tmp_path / "out.geojson"
    sidecar = output.with_suffix(suffix)
    sidecar.symlink_to(output)
    with pytest.raises(ValueError, match="export paths must be distinct"):
        export_boundaries(
            BoundaryCollection.model_validate(collection()),
            output,
            credit="Synthetic",
        )
    assert not output.exists()
    assert list(tmp_path.iterdir()) == [sidecar]


@pytest.mark.parametrize("suffix", [".geojson", ".provenance.json", ".credit.txt"])
def test_database_destination_rejected(tmp_path: Path, suffix: str) -> None:
    db = tmp_path / ("out" + suffix)
    database(db, keys())
    before = db.read_bytes()
    with pytest.raises(ValueError, match="export paths must be distinct"):
        export_boundaries(
            BoundaryCollection.model_validate(collection()),
            tmp_path / "out.geojson",
            facts_db=db,
            credit="Synthetic",
        )
    assert db.read_bytes() == before
    assert list(tmp_path.iterdir()) == [db]
