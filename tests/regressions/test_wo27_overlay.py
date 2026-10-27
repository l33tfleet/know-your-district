"""WO-79: offline TIGER loading and unmodified exported geometry agreement."""

import copy
import io
import json
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Any, Literal
from zipfile import ZipFile

import pytest
from pyproj import CRS, Transformer

from etl.boundaries.overlay import EQUAL_AREA_CRS, agreement, compare_export, load_tiger_archive

# pyshp has no py.typed marker; keep its dynamic API at the fixture boundary.
shapefile: Any = import_module("shapefile")

FIXTURE = Path(__file__).parent / "fixtures/wo27_overlay.json"


def fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("case", fixture()["cases"], ids=lambda case: case["name"])
def test_intersection_over_union(case: dict[str, Any]) -> None:
    assert agreement(case["left"], case["right"]) == pytest.approx(case["agreement"])
    assert agreement(case["right"], case["left"]) == pytest.approx(case["agreement"])


@pytest.mark.parametrize("case", list(fixture()["invalid"]))
def test_invalid_geometry_is_never_repaired(case: str) -> None:
    geometry = fixture()["invalid"][case]
    before = copy.deepcopy(geometry)
    messages = {
        "self_intersection": "self-intersection",
        "outside_hole": "hole outside shell",
        "crossing_hole": "intersecting rings",
        "nested_holes": "nested holes",
        "overlapping_parts": "overlapping multipolygon parts",
        "zero_area": "zero area",
        "open_ring": "open ring",
        "empty": "invalid geometry",
        "wrong_type": "invalid geometry",
        "repeated_vertex": "repeated vertex",
        "shared_edge": "shared multipolygon edge",
        "nonfinite": "finite number",
    }
    with pytest.raises(ValueError, match=messages[case]):
        agreement(geometry, fixture()["cases"][0]["left"])
    assert geometry == before


def keys(chamber: str, limit: int) -> list[str]:
    return [f"{chamber}:15:{number:03}:2022" for number in range(1, limit + 1)]


def archive(
    tmp_path: Path,
    chamber: Literal["house", "senate"],
    *,
    count: int | None = None,
    state: str = "15",
    geoid: str | None = None,
    duplicate: bool = False,
    prj: bool = True,
    extra: bool = False,
    epsg: int = 4326,
    rings: list[list[list[float]]] | None = None,
    invalid_crs: bool = False,
    point: bool = False,
    district_override: str | None = None,
) -> Path:
    code = "SLDLST" if chamber == "house" else "SLDUST"
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=1 if point else 5) as writer:
        writer.field("STATEFP", "C")
        writer.field(code, "C")
        writer.field("GEOID", "C")
        for number in range(
            1, (count if count is not None else (51 if chamber == "house" else 25)) + 1
        ):
            district = district_override or ("001" if duplicate else f"{number:03}")
            writer.record(state, district, geoid or state + district)
            if point:
                writer.point(-158, 20)
            else:
                writer.poly(
                    rings
                    if rings is not None
                    else [[[-158, 20], [-158, 21], [-157, 21], [-157, 20], [-158, 20]]]
                )
    path = tmp_path / f"{chamber}.zip"
    with ZipFile(path, "w") as zipped:
        for suffix, stream in (("shp", shp), ("shx", shx), ("dbf", dbf)):
            zipped.writestr(f"districts.{suffix}", stream.getvalue())
        if prj:
            zipped.writestr(
                "districts.prj", "invalid CRS" if invalid_crs else CRS.from_epsg(epsg).to_wkt()
            )
        if extra:
            zipped.writestr("other.shp", shp.getvalue())
    return path


def exported(tmp_path: Path) -> Path:
    path = tmp_path / "export.geojson"
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-158, 20], [-157, 20], [-157, 21], [-158, 21], [-158, 20]]],
    }
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": key,
                        "properties": {"chamber": chamber, "district": number},
                        "geometry": geometry,
                    }
                    for chamber, count in (("house", 51), ("senate", 25))
                    for number, key in enumerate(keys(chamber, count), 1)
                ],
            }
        )
    )
    path.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                "source_url": "https://example.org/state/2022",
                "retrieved_on": "2026-01-01",
                "vintage": "2022 plan",
                "plan_year": 2022,
                "method": "synthetic export",
            }
        )
    )
    return path


def test_load_both_chambers_with_qualified_ids(tmp_path: Path) -> None:
    chambers: list[tuple[Literal["house", "senate"], int]] = [("house", 51), ("senate", 25)]
    for chamber, count in chambers:
        result = load_tiger_archive(archive(tmp_path, chamber), chamber)
        assert sorted(result) == keys(chamber, count)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"count": 50}, "district set mismatch"),
        ({"state": "06"}, "FIPS 15"),
        ({"geoid": "15002"}, "GEOID mismatch"),
        ({"duplicate": True}, "duplicate district"),
        ({"prj": False}, "archive requires"),
        ({"extra": True}, "archive requires"),
        ({"point": True}, "TIGER shape must be a Polygon"),
        ({"district_override": "052"}, "district must be in 1..51"),
    ],
)
def test_reject_bad_archives(tmp_path: Path, options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_tiger_archive(archive(tmp_path, "house", **options), "house")


def test_compare_reports_every_agreement_and_every_shortfall(tmp_path: Path) -> None:
    path = exported(tmp_path)
    data = json.loads(path.read_text())
    for feature in data["features"][:2]:
        feature["geometry"]["coordinates"][0][1][0] = -157.1
        feature["geometry"]["coordinates"][0][2][0] = -157.1
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    output = io.StringIO()
    results = compare_export(
        path, archive(tmp_path, "house"), archive(tmp_path, "senate"), output=output
    )
    assert len(results) == 76
    assert sum(result.agreement < 99 for result in results) == 2
    report = output.getvalue()
    for key in keys("house", 51) + keys("senate", 25):
        assert key in report
    assert report.count("BELOW 99%") == 2
    assert "shortfall=" in report
    assert "https://example.org/state/2022" in report
    assert "house.zip" in report and "senate.zip" in report
    assert EQUAL_AREA_CRS in report and "100*intersection/union" in report
    assert path.read_bytes() == before
    # Independent analytic area for this cylindrical equal-area projection:
    # the narrowed longitude interval has 90% of the original area.
    assert results[0].agreement == pytest.approx(90, abs=1e-7)
    assert results[0].shortfall == pytest.approx(9, abs=1e-7)
    assert all(result.agreement == pytest.approx(100) for result in results[2:])
    transformer = Transformer.from_crs(4326, EQUAL_AREA_CRS, always_xy=True)
    assert transformer.target_crs is not None
    assert transformer.target_crs.coordinate_operation is not None
    assert "Equal Area" in transformer.target_crs.coordinate_operation.method_name


@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("missing", "export district set mismatch"),
        ("extra", "export district set mismatch"),
        ("duplicate", "duplicate export district"),
        ("unqualified", "export district set mismatch"),
        ("properties", "export identity mismatch"),
        ("invalid", "invalid geometry"),
        ("provenance", "plan_year"),
    ],
)
def test_reject_bad_exports(tmp_path: Path, problem: str, message: str) -> None:
    path = exported(tmp_path)
    data = json.loads(path.read_text())
    if problem == "missing":
        data["features"].pop()
    elif problem == "extra":
        data["features"].append({**data["features"][0], "id": "house:15:052:2022"})
    elif problem == "duplicate":
        data["features"].append(data["features"][0])
    elif problem == "unqualified":
        data["features"][0]["id"] = "house-01"
    elif problem == "properties":
        data["features"][0]["properties"]["chamber"] = "senate"
    elif problem == "invalid":
        data["features"][0]["geometry"] = fixture()["invalid"]["self_intersection"]
    else:
        sidecar = path.with_suffix(".provenance.json")
        provenance = json.loads(sidecar.read_text())
        provenance["plan_year"] = 2012
        sidecar.write_text(json.dumps(provenance))
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        compare_export(
            path, archive(tmp_path, "house"), archive(tmp_path, "senate"), output=io.StringIO()
        )


def test_cli_offline_and_failing_disagreements(tmp_path: Path) -> None:
    path = exported(tmp_path)
    house, senate = archive(tmp_path, "house"), archive(tmp_path, "senate")
    command = [sys.executable, "-m", "etl.boundaries.overlay", str(path), str(house), str(senate)]
    success = subprocess.run(command, capture_output=True, text=True, check=False)
    assert success.returncode == 0, success.stderr
    assert "house:15:001:2022" in success.stdout
    data = json.loads(path.read_text())
    data["features"][0]["geometry"]["coordinates"][0][1][0] = -157.5
    path.write_text(json.dumps(data))
    failure = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failure.returncode == 1
    assert "BELOW 99%" in failure.stdout
    path.unlink()
    failure = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failure.returncode == 1
    assert "Overlay failed" in failure.stderr


def test_archive_crs_is_used(tmp_path: Path) -> None:
    result = load_tiger_archive(archive(tmp_path, "house", epsg=4269), "house")
    expected = Transformer.from_crs(4269, EQUAL_AREA_CRS, always_xy=True).transform(-158, 20)
    assert result["house:15:001:2022"][0][0][0] == pytest.approx(expected)


def test_archive_preserves_holes_and_disconnected_parts(tmp_path: Path) -> None:
    rings: list[list[list[float]]] = [
        [[-158, 20], [-158, 21], [-157, 21], [-157, 20], [-158, 20]],
        [[-157.8, 20.2], [-157.2, 20.2], [-157.2, 20.8], [-157.8, 20.8], [-157.8, 20.2]],
        [[-156, 20], [-156, 21], [-155, 21], [-155, 20], [-156, 20]],
    ]
    result = load_tiger_archive(archive(tmp_path, "house", rings=rings), "house")
    assert sorted(map(len, result["house:15:001:2022"])) == [1, 2]


def test_archive_rejects_orphan_holes_without_reclassifying(tmp_path: Path) -> None:
    rings: list[list[list[float]]] = [
        [[-158, 20], [-158, 21], [-157, 21], [-157, 20], [-158, 20]],
        [[-156, 20], [-155, 20], [-155, 21], [-156, 21], [-156, 20]],
    ]
    with pytest.raises(ValueError, match="invalid geometry: orphan shapefile hole"):
        load_tiger_archive(archive(tmp_path, "house", rings=rings), "house")


def test_archive_rejects_invalid_crs(tmp_path: Path) -> None:
    from pyproj.exceptions import CRSError

    with pytest.raises(CRSError):
        load_tiger_archive(archive(tmp_path, "house", invalid_crs=True), "house")


@pytest.mark.parametrize("problem", ["type", "features"])
def test_reject_invalid_export_envelope(tmp_path: Path, problem: str) -> None:
    path = exported(tmp_path)
    data = json.loads(path.read_text())
    data[problem] = "invalid"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid export FeatureCollection"):
        compare_export(path, archive(tmp_path, "house"), archive(tmp_path, "senate"))


def test_invalid_source_topology_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid geometry: self-intersection"):
        load_tiger_archive(
            archive(
                tmp_path, "house", rings=fixture()["invalid"]["self_intersection"]["coordinates"]
            ),
            "house",
        )


def test_nonobject_export_is_rejected(tmp_path: Path) -> None:
    path = exported(tmp_path)
    path.write_text("[]")
    with pytest.raises(ValueError, match="Input should be an object"):
        compare_export(path, archive(tmp_path, "house"), archive(tmp_path, "senate"))
