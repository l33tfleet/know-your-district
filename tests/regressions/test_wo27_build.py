"""WO-80: offline orchestration uses State shapes, TIGER overlays and actual SQL keys."""

import io
import json
import sqlite3
import subprocess
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from pyproj import CRS

from etl.boundaries.state import BASE_URL, LAYERS

shapefile: Any = import_module("shapefile")
ROOT = Path(__file__).resolve().parents[2]
COUNTS = {"house": 51, "senate": 25}


def sources(path: Path, *, mismatch: bool = False) -> None:
    path.mkdir()
    for chamber, (layer, _) in LAYERS.items():
        count = COUNTS[chamber]
        ring = [[-158, 20], [-158, 21], [-157, 21], [-157, 20], [-158, 20]]
        features: list[dict[str, Any]] = [
            {
                "type": "Feature",
                "properties": {f"{chamber}_id": number},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
            for number in range(1, count + 1)
        ]
        if mismatch and chamber == "senate":
            features[0]["geometry"] = {
                "type": "Polygon",
                "coordinates": [[[-158, 20], [-158, 21], [-157.5, 21], [-157.5, 20], [-158, 20]]],
            }
        (path / f"state-{chamber}.json").write_text(
            json.dumps({"type": "FeatureCollection", "features": features})
        )
        shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=5) as writer:
            writer.field("STATEFP", "C")
            writer.field("SLDLST" if layer == 33 else "SLDUST", "C")
            writer.field("GEOID", "C")
            for number in range(1, count + 1):
                writer.record("15", f"{number:03}", f"15{number:03}")
                writer.poly([ring])
        code = "sldl" if chamber == "house" else "sldu"
        with ZipFile(path / f"tl_2022_15_{code}.zip", "w") as archive:
            for suffix, stream in (("shp", shp), ("shx", shx), ("dbf", dbf)):
                archive.writestr(f"districts.{suffix}", stream.getvalue())
            archive.writestr("districts.prj", CRS.from_epsg(4326).to_wkt())


def facts(path: Path, *, missing: bool = False, extra: bool = False) -> None:
    keys = [
        f"{chamber}:15:{number:03}:2022"
        for chamber, count in COUNTS.items()
        for number in range(1, count + 1)
    ]
    if missing:
        keys.remove("senate:15:025:2022")
    if extra:
        keys.append("house:15:052:2022")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE facts (geography TEXT)")
        db.executemany("INSERT INTO facts VALUES (?)", [(key,) for key in keys])


def build(source: Path, output: Path, database: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "etl.boundaries.build",
            "--source-dir",
            str(source),
            "--output-dir",
            str(output),
            "--facts-db",
            str(database),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_default_make_builds_and_local_validation_is_preserved() -> None:
    default = subprocess.run(
        ["make", "-n", "boundaries"], capture_output=True, text=True, check=True
    )
    assert "-m etl.boundaries.build" in default.stdout
    fixture = ROOT / "tests/regressions/fixtures/wo47_boundaries.geojson"
    local = subprocess.run(
        ["make", "boundaries", f"BOUNDARIES_FILE={fixture}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert local.returncode == 0, local.stderr
    assert [
        line for line in local.stdout.splitlines() if line.startswith(("house-", "senate-"))
    ] == ["house-01", "senate-01"]
    invalid = subprocess.run(
        ["make", "boundaries", "BOUNDARIES_FILE=/nonexistent/boundaries.geojson"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode != 0
    assert "Boundary validation failed:" in invalid.stderr


@pytest.mark.parametrize("mismatch", [False, True])
def test_offline_build_rebuilds_both_shapes_and_publishes_evidence(
    tmp_path: Path, mismatch: bool
) -> None:
    source, output, database = tmp_path / "source", tmp_path / "geo", tmp_path / "facts.sqlite"
    sources(source, mismatch=mismatch)
    facts(database)
    before = database.read_bytes()
    for _ in range(2):
        result = build(source, output, database)
        assert result.returncode == 0, result.stderr
        for chamber, (layer, credit) in LAYERS.items():
            count = COUNTS[chamber]
            path = output / f"{chamber}.geojson"
            document = json.loads(path.read_text())
            assert len(document["features"]) == count
            assert document["features"][0]["id"] == f"{chamber}:15:001:2022"
            provenance = json.loads(path.with_suffix(".provenance.json").read_text())
            assert provenance["source_url"].startswith(f"{BASE_URL}/{layer}/query?")
            assert provenance["plan_year"] == 2022
            assert date.fromisoformat(provenance["retrieved_on"])
            assert path.with_suffix(".credit.txt").read_text().strip() == credit
            path.write_text("stale")
        report = (output / "overlay.md").read_text()
        assert report.count("agreement=") == 76
        assert "EPSG:6933" in report
        mismatch_report = (output / "mismatch.md").read_text()
        if mismatch:
            assert "senate:15:001:2022" in mismatch_report
            assert "BELOW 99%" in mismatch_report
            assert "shortfall=" in mismatch_report
            assert f"{BASE_URL}/34/query?" in mismatch_report
        else:
            assert "No districts below 99%" in mismatch_report
        proof = (output / "fact-keys.md").read_text()
        assert "PASS" in proof and str(database.resolve()) in proof
        assert "missing=[]" in proof and "extra=[]" in proof
        assert "sha256=" in proof
    assert database.read_bytes() == before


@pytest.mark.parametrize("problem", ["absent", "missing", "extra"])
def test_build_cannot_claim_join_proof_without_matching_database(
    tmp_path: Path, problem: str
) -> None:
    source, output, database = tmp_path / "source", tmp_path / "geo", tmp_path / "facts.sqlite"
    sources(source)
    if problem != "absent":
        facts(database, missing=problem == "missing", extra=problem == "extra")
    result = build(source, output, database)
    assert result.returncode != 0
    proof = (output / "fact-keys.md").read_text()
    assert "PASS" not in proof
    if problem == "absent":
        assert "#24" in proof and "unavailable" in proof
        assert not database.exists()
    else:
        assert "fact key mismatch" in proof
        assert ("senate:15:025:2022" if problem == "missing" else "house:15:052:2022") in proof
    assert "Boundary build failed:" in result.stderr
    assert "Traceback" not in result.stderr


def test_build_reports_source_failure(tmp_path: Path) -> None:
    source = tmp_path / "source"
    sources(source)
    (source / "state-house.json").write_text('{"error": {"message": "offline failure"}}')
    result = build(source, tmp_path / "geo", tmp_path / "facts.sqlite")
    assert result.returncode != 0
    assert "Boundary build failed: ArcGIS service error" in result.stderr
    assert "Traceback" not in result.stderr


def test_invalid_state_topology_is_published_as_unverified_mismatch(tmp_path: Path) -> None:
    source, output, database = tmp_path / "source", tmp_path / "geo", tmp_path / "facts.sqlite"
    sources(source)
    facts(database)
    path = source / "state-house.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["geometry"]["coordinates"] = [
        [[-158, 20], [-155, 23], [-158, 23], [-156, 20], [-158, 20]]
    ]
    path.write_text(json.dumps(payload))
    result = build(source, output, database)
    assert result.returncode == 0, result.stderr
    report = (output / "mismatch.md").read_text()
    assert "house:15:001:2022" in report
    assert "UNVERIFIED" in report and "invalid geometry: self-intersection" in report
    assert "agreement=" not in report
    document = json.loads((output / "house.geojson").read_text())
    assert document["features"][0]["geometry"] == payload["features"][0]["geometry"]
    assert (output / "overlay.md").read_text().count("agreement=") == 75


@pytest.mark.parametrize("alias", [False, True])
def test_output_cannot_overwrite_fact_database(tmp_path: Path, alias: bool) -> None:
    source, output = tmp_path / "source", tmp_path / "geo"
    sources(source)
    output.mkdir()
    database = tmp_path / "facts.sqlite" if alias else output / "house.geojson"
    facts(database)
    if alias:
        (output / "senate.provenance.json").symlink_to(database)
    before = database.read_bytes()
    result = build(source, output, database)
    assert result.returncode != 0
    assert "output paths must be distinct from each other and the fact database" in result.stderr
    assert database.read_bytes() == before


def test_overlay_computation_failure_is_evidence_not_an_agreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etl.boundaries import build as builder

    source, output, database = tmp_path / "source", tmp_path / "geo", tmp_path / "facts.sqlite"
    sources(source)
    facts(database)

    def unavailable(*_args: object) -> float:
        raise ValueError("synthetic overlay computation failure")

    monkeypatch.setattr(builder, "agreement", unavailable, raising=False)
    builder.build_boundaries(output, database, source)
    report = (output / "mismatch.md").read_text()
    assert report.count("UNVERIFIED") == 76
    assert "synthetic overlay computation failure" in report
    assert "agreement=" not in report


def test_duplicate_output_destinations_are_rejected(tmp_path: Path) -> None:
    source, output, database = tmp_path / "source", tmp_path / "geo", tmp_path / "facts.sqlite"
    sources(source)
    output.mkdir()
    (output / "senate.geojson").symlink_to(output / "house.geojson")
    result = build(source, output, database)
    assert result.returncode != 0
    assert "output paths must be distinct from each other and the fact database" in result.stderr
    assert not (output / "house.geojson").exists()


def test_invalid_tiger_archive_fails_without_publishing(tmp_path: Path) -> None:
    source, output, database = tmp_path / "source", tmp_path / "geo", tmp_path / "facts.sqlite"
    sources(source)
    (source / "tl_2022_15_sldl.zip").write_bytes(b"not a zip")
    result = build(source, output, database)
    assert result.returncode != 0
    assert "Boundary build failed: File is not a zip file" in result.stderr
    assert not list(output.iterdir())


def test_published_state_shapes_and_every_unaccepted_overlay_have_evidence() -> None:
    output = ROOT / "data/geo"
    overlay = (output / "overlay.md").read_text()
    mismatch = (output / "mismatch.md").read_text()
    for chamber, (layer, credit) in LAYERS.items():
        count = COUNTS[chamber]
        path = output / f"{chamber}.geojson"
        document = json.loads(path.read_text())
        assert {feature["id"] for feature in document["features"]} == {
            f"{chamber}:15:{number:03}:2022" for number in range(1, count + 1)
        }
        assert path.stat().st_size < 1_000_000
        provenance = json.loads(path.with_suffix(".provenance.json").read_text())
        assert provenance["source_url"].startswith(f"{BASE_URL}/{layer}/query?")
        assert path.with_suffix(".credit.txt").read_text().strip() == credit
        for number in range(1, count + 1):
            key = f"{chamber}:15:{number:03}:2022"
            lines = [line for line in overlay.splitlines() if line.startswith(key + ":")]
            assert len(lines) == 1
            if "; OK;" not in lines[0]:
                assert lines[0] in mismatch
    assert "#24" in (ROOT / "docs/data.md").read_text()
