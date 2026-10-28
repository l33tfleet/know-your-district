"""WO121: reproduce county intersections offline and reject incomplete boundary inputs."""

import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from pyproj import CRS

from app.counties import load_mapping
from etl.boundaries.counties import build_mapping, load_counties
from etl.boundaries.overlay import shapefile
from tests.regressions.test_wo27_overlay import exported


def county_archive(
    tmp_path: Path, *, missing: str = "", duplicate: bool = False, geoid: bool = False
) -> Path:
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=5) as writer:
        for name in ("STATEFP", "COUNTYFP", "GEOID"):
            writer.field(name, "C")
        codes = ["001", "003", "005", "007", "009"] + (["001"] if duplicate else [])
        for code in codes:
            if code == missing:
                continue
            writer.record("15", code, "XX" if geoid and code == "001" else "15" + code)
            # District fixture is inside county 001, other counties are disjoint.
            left = -159 if code == "001" else -151 + codes.index(code)
            writer.poly([[[left, 19], [left, 22], [left + 3, 22], [left + 3, 19], [left, 19]]])
        # An out-of-state record must be ignored even if its county code is configured.
        writer.record("01", "001", "01001")
        writer.poly([[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]])
    path = tmp_path / "county.zip"
    with ZipFile(path, "w") as archive:
        for suffix, stream in (("shp", shp), ("shx", shx), ("dbf", dbf)):
            if suffix != missing:
                archive.writestr(f"county.{suffix}", stream.getvalue())
        if missing != "prj":
            archive.writestr("county.prj", CRS.from_epsg(4326).to_wkt())
    return path


def districts(tmp_path: Path) -> tuple[Path, Path]:
    source = exported(tmp_path)
    document = json.loads(source.read_text())
    paths: list[Path] = []
    for chamber in ("house", "senate"):
        path = tmp_path / f"{chamber}.geojson"
        path.write_text(
            json.dumps(
                document
                | {
                    "features": [
                        f for f in document["features"] if f["properties"]["chamber"] == chamber
                    ]
                }
            )
        )
        path.with_suffix(".provenance.json").write_bytes(
            source.with_suffix(".provenance.json").read_bytes()
        )
        path.with_suffix(".credit.txt").write_text("Synthetic boundary credit")
        paths.append(path)
    return paths[0], paths[1]


def test_offline_build_covers_76_excludes_kalawao_and_preserves_provenance(tmp_path: Path) -> None:
    house, senate = districts(tmp_path)
    output = tmp_path / "mapping.tsv"
    build_mapping(house, senate, county_archive(tmp_path), output)
    mapping = load_mapping(output)
    assert len(mapping) == 76
    assert all([s.county for s in shares] == ["county:15:001"] for shares in mapping.values())
    provenance = json.loads(output.with_suffix(".provenance.json").read_text())
    assert provenance["district_sources"][0]["credit"] == "Synthetic boundary credit"
    assert len(provenance["county_sha256"]) == 64


@pytest.mark.parametrize(
    "missing,message",
    [
        ("shp", "exactly one shapefile"),
        ("shx", "matching .shp/.shx/.dbf/.prj"),
        ("prj", "matching .shp/.shx/.dbf/.prj"),
        ("009", "county set mismatch"),
    ],
)
def test_incomplete_county_archive_fails(tmp_path: Path, missing: str, message: str) -> None:
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        load_counties(county_archive(tmp_path, missing=missing))


def test_duplicate_county_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate county: 001"):
        load_counties(county_archive(tmp_path, duplicate=True))


def test_county_identity_mismatch_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="county GEOID mismatch"):
        load_counties(county_archive(tmp_path, geoid=True))


@pytest.mark.parametrize(
    "error,message",
    [("identity", "export identity mismatch"), ("missing", "district set mismatch")],
)
def test_bad_district_export_fails_before_write(tmp_path: Path, error: str, message: str) -> None:
    house, senate = districts(tmp_path)
    document = json.loads(house.read_text())
    if error == "identity":
        document["features"][0]["id"] = "house:15:002:2022"
    else:
        document["features"].pop()
    house.write_text(json.dumps(document))
    output = tmp_path / "mapping.tsv"
    with pytest.raises(ValueError, match=message):
        build_mapping(house, senate, county_archive(tmp_path), output)
    assert not output.exists()
