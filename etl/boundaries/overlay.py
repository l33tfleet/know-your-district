"""Offline comparison of exported 2022 boundaries to FIPS-15 TIGER SLDL/SLDU.

Run: uv run python -m etl.boundaries.overlay EXPORT.geojson SLDL.zip SLDU.zip
Use the Census 2022 TIGER/Line archives tl_2022_15_sldl.zip and
tl_2022_15_sldu.zip; their .prj supplies the input CRS. The export is WGS84,
with the .provenance.json sidecar written by production.export_boundaries.
Archive paths and export provenance identify both inputs in every result.

Areas use EPSG:6933 (WGS 84 / NSIDC EASE-Grid 2.0 Global), a cylindrical
equal-area CRS in metres covering Hawaiʻi. Project vertices with always_xy;
straight projected segments define the compared geometry. No snapping,
simplification, buffering, repair, or tolerance-based acceptance is performed.
Agreement is 100*intersection/union; shortfall is max(0, 99-agreement) in
percentage points. Disagreements are printed and produce CLI exit status 1.

The planar overlay integrates vertical strips, split at every vertex and edge
intersection. Within each strip, interval endpoints are linear, so midpoint
integration is exact for these polygons. Even/odd ring intervals preserve
holes and disconnected parts. This uses only the pinned pyproj/pyshp stack.
"""

import argparse
import io
import math
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal, TextIO
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, Field, FiniteFloat, TypeAdapter, ValidationError
from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError

from etl.boundaries import Chamber, DistrictId, Provenance, expected_fact_keys
from etl.boundaries import MultiPolygon as InputMultiPolygon
from etl.boundaries import Polygon as InputPolygon

# pyshp has no py.typed marker; isolate its dynamic shapefile API here.
shapefile: Any = import_module("shapefile")

EQUAL_AREA_CRS = "EPSG:6933"
Point = tuple[float, float]
Segment = tuple[Point, Point]
Ring = list[Point]
Polygon = list[Ring]
Geometry = list[Polygon]


class _Polygon(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[Annotated[list[tuple[FiniteFloat, FiniteFloat]], Field(min_length=4)]] = (
        Field(min_length=1)
    )


class _MultiPolygon(BaseModel):
    type: Literal["MultiPolygon"]
    coordinates: list[
        Annotated[
            list[Annotated[list[tuple[FiniteFloat, FiniteFloat]], Field(min_length=4)]],
            Field(min_length=1),
        ]
    ] = Field(min_length=1)


def _segments(ring: Ring) -> list[Segment]:
    return list(pairwise(ring))


def _edges(geometry: Geometry) -> list[Segment]:
    return [edge for polygon in geometry for ring in polygon for edge in _segments(ring)]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _on(point: Point, segment: Segment) -> bool:
    a, b = segment
    return (
        _cross(_sub(point, a), _sub(b, a)) == 0
        and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
    )


def _intersections(a: Segment, b: Segment) -> list[Point]:
    p, q = a
    r, s = b
    u, v, w = _sub(q, p), _sub(s, r), _sub(r, p)
    determinant = _cross(u, v)
    if determinant == 0:
        return sorted({point for point in (*a, *b) if _on(point, a) and _on(point, b)})
    t, fraction = _cross(w, v) / determinant, _cross(w, u) / determinant
    if 0 <= t <= 1 and 0 <= fraction <= 1:
        return [(p[0] + t * u[0], p[1] + t * u[1])]
    return []


def _pairs(edges: list[Segment]) -> Iterator[tuple[int, int]]:
    """Sweep bounding boxes instead of comparing every pair of coastline edges."""
    active: list[int] = []
    for index in sorted(range(len(edges)), key=lambda i: min(p[0] for p in edges[i])):
        edge = edges[index]
        xmin = min(p[0] for p in edge)
        active = [i for i in active if max(p[0] for p in edges[i]) >= xmin]
        ymin, ymax = sorted(p[1] for p in edge)
        for other in active:
            low, high = sorted(p[1] for p in edges[other])
            if low <= ymax and high >= ymin:
                yield other, index
        active.append(index)


def _inside(point: Point, ring: Ring) -> bool:
    x, y = point
    result = False
    for (ax, ay), (bx, by) in _segments(ring):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            result = not result
    return result


def _signed_area(ring: Ring) -> float:
    # Translate first to avoid cancellation from large projected coordinates.
    origin = ring[0]
    return math.fsum(_cross(_sub(a, origin), _sub(b, origin)) for a, b in _segments(ring)) / 2


def _validate(geometry: Geometry) -> None:
    for polygon in geometry:
        for ring in polygon:
            if ring[0] != ring[-1] or len(set(ring[:-1])) != len(ring) - 1:
                raise ValueError("invalid geometry: open ring or repeated vertex")
            if _signed_area(ring) == 0:
                raise ValueError("invalid geometry: zero area")
            edges = _segments(ring)
            for i, j in _pairs(edges):
                hits = _intersections(edges[i], edges[j])
                adjacent = abs(i - j) == 1 or {i, j} == {0, len(edges) - 1}
                if hits and not (adjacent and len(hits) == 1):
                    raise ValueError("invalid geometry: self-intersection")
        for i, ring in enumerate(polygon):
            for other in polygon[:i]:
                edges = _segments(ring) + _segments(other)
                split = len(ring) - 1
                if any(
                    _intersections(edges[a], edges[b])
                    for a, b in _pairs(edges)
                    if (a < split) != (b < split)
                ):
                    raise ValueError("invalid geometry: intersecting rings")
            if i and not _inside(ring[0], polygon[0]):
                raise ValueError("invalid geometry: hole outside shell")
            if i and any(
                _inside(ring[0], other) or _inside(other[0], ring) for other in polygon[1:i]
            ):
                raise ValueError("invalid geometry: nested holes")
    for i, polygon in enumerate(geometry):
        for other in geometry[:i]:
            if _areas([polygon], [other])[2] > 0:
                raise ValueError("invalid geometry: overlapping multipolygon parts")
            edges = _edges([polygon]) + _edges([other])
            split = len(_edges([polygon]))
            if any(
                len(_intersections(edges[a], edges[b])) > 1
                for a, b in _pairs(edges)
                if (a < split) != (b < split)
            ):
                raise ValueError("invalid geometry: shared multipolygon edge")


def _geometry(value: object, transformer: Transformer | None = None) -> Geometry:
    try:
        model = TypeAdapter(_Polygon | _MultiPolygon).validate_python(value)
    except ValidationError as exc:
        raise ValueError(f"invalid geometry: {exc}") from exc
    polygons = [model.coordinates] if isinstance(model, _Polygon) else model.coordinates
    _validate(polygons)
    if transformer is not None:
        polygons = [
            [[transformer.transform(x, y, errcheck=True) for x, y in ring] for ring in polygon]
            for polygon in polygons
        ]
        _validate(polygons)
    return polygons


def _intervals(edges: list[Segment], x: float) -> list[tuple[float, float]]:
    ys = sorted(
        a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
        for a, b in edges
        if min(a[0], b[0]) < x < max(a[0], b[0])
    )
    return list(zip(ys[::2], ys[1::2], strict=True))


def _areas(left: Geometry, right: Geometry) -> tuple[float, float, float]:
    a, b = _edges(left), _edges(right)
    edges = a + b
    cuts = {point[0] for edge in edges for point in edge}
    cuts.update(point[0] for i, j in _pairs(edges) for point in _intersections(edges[i], edges[j]))
    ordered = sorted(cuts)
    starts: dict[float, list[int]] = {}
    ends: dict[float, list[int]] = {}
    for index, (p, q) in enumerate(edges):
        low, high = sorted((p[0], q[0]))
        if low != high:
            starts.setdefault(low, []).append(index)
            ends.setdefault(high, []).append(index)
    active: set[int] = set()
    left_areas: list[float] = []
    right_areas: list[float] = []
    overlaps: list[float] = []
    for low, high in pairwise(ordered):
        width = high - low
        x = low + width / 2
        active.difference_update(ends.get(low, []))
        active.update(starts.get(low, []))
        ia = _intervals([edges[i] for i in active if i < len(a)], x)
        ib = _intervals([edges[i] for i in active if i >= len(a)], x)
        left_areas.append(width * math.fsum(y - x for x, y in ia))
        right_areas.append(width * math.fsum(y - x for x, y in ib))
        overlaps.append(
            width * math.fsum(max(0, min(v, z) - max(u, w)) for u, v in ia for w, z in ib)
        )
    return math.fsum(left_areas), math.fsum(right_areas), math.fsum(overlaps)


def _agreement(left: Geometry, right: Geometry) -> float:
    a, b, overlap = _areas(left, right)
    return 100 * overlap / (a + b - overlap)


def agreement(left: object, right: object) -> float:
    """Compare already projected equal-area Polygon/MultiPolygon GeoJSON objects."""
    return _agreement(_geometry(left), _geometry(right))


def _shapefile_geometry(shape: Any) -> dict[str, object]:
    """Preserve shapefile ring roles; never promote an orphan hole to a shell."""
    if shape.shapeType != 5:
        raise ValueError("invalid geometry: TIGER shape must be a Polygon")
    points: list[Point] = [tuple(point) for point in shape.points]
    parts: list[int] = [*shape.parts, len(points)]
    rings = [points[a:b] for a, b in pairwise(parts)]
    # Validate rings before reading orientation or assigning holes.
    for ring in rings:
        _geometry({"type": "Polygon", "coordinates": [ring]})
    shells = [[ring] for ring in rings if _signed_area(ring) < 0]
    for hole in (ring for ring in rings if _signed_area(ring) > 0):
        parents = [shell for shell in shells if _inside(hole[0], shell[0])]
        if not parents:
            raise ValueError("invalid geometry: orphan shapefile hole")
        min(parents, key=lambda shell: abs(_signed_area(shell[0]))).append(hole)
    return {"type": "MultiPolygon", "coordinates": shells}


def load_tiger_archive(path: Path, chamber: Chamber) -> dict[str, Geometry]:
    """Read a local 2022 TIGER ZIP in memory, without extracting archive paths.

    The operator supplies the plan vintage by selecting the documented archive;
    STATEFP, GEOID and SLDLST/SLDUST must agree. The .prj is mandatory.
    Return complete, validated, equal-area geometry keyed by qualified fact IDs.
    """
    result: dict[str, Geometry] = {}
    with ZipFile(path) as archive:
        names = archive.namelist()
        shapes = [name for name in names if name.lower().endswith(".shp")]
        if len(shapes) != 1:
            raise ValueError("archive requires exactly one shapefile")
        stem = shapes[0][:-4]
        members = [stem + suffix for suffix in (".shp", ".shx", ".dbf", ".prj")]
        if any(names.count(member) != 1 for member in members):
            raise ValueError("archive requires matching .shp/.shx/.dbf/.prj")
        transformer = Transformer.from_crs(
            CRS.from_wkt(archive.read(members[3]).decode("utf-8")), EQUAL_AREA_CRS, always_xy=True
        )
        with shapefile.Reader(
            shp=io.BytesIO(archive.read(members[0])),
            shx=io.BytesIO(archive.read(members[1])),
            dbf=io.BytesIO(archive.read(members[2])),
        ) as reader:
            for record in reader.iterShapeRecords():
                attributes: dict[str, Any] = record.record.as_dict()
                if attributes.get("STATEFP") != "15":
                    raise ValueError("TIGER archive must contain only FIPS 15")
                district = DistrictId.model_validate(
                    {
                        "chamber": chamber,
                        "district": attributes.get("SLDLST" if chamber == "house" else "SLDUST"),
                    }
                )
                if attributes.get("GEOID") != "15" + district.census_code:
                    raise ValueError("TIGER GEOID mismatch")
                key = district.fact_key
                if key in result:
                    raise ValueError(f"duplicate district: {key}")
                result[key] = _geometry(_shapefile_geometry(record.shape), transformer)
    expected = expected_fact_keys(chamber)
    if set(result) != expected:
        raise ValueError(
            f"district set mismatch: missing={sorted(expected - result.keys())}, extra={sorted(result.keys() - expected)}"
        )
    return result


@dataclass(frozen=True)
class Agreement:
    key: str
    agreement: float

    @property
    def shortfall(self) -> float:
        return max(0, 99 - self.agreement)


def compare_export(
    exported: Path, sldl: Path, sldu: Path, *, output: TextIO | None = None
) -> list[Agreement]:
    """Compare complete exported geometry, printing all results before returning."""
    stream = sys.stdout if output is None else output
    provenance = Provenance.model_validate_json(
        exported.with_suffix(".provenance.json").read_text()
    )
    document = TypeAdapter(dict[str, Any]).validate_json(exported.read_text())
    if document.get("type") != "FeatureCollection" or not isinstance(
        document.get("features"), list
    ):
        raise ValueError("invalid export FeatureCollection")
    features: dict[str, dict[str, Any]] = {}
    for feature in document["features"]:
        key = feature["id"]
        if key in features:
            raise ValueError(f"duplicate export district: {key}")
        features[key] = feature
    expected = expected_fact_keys()
    if features.keys() != expected:
        raise ValueError(
            f"export district set mismatch: missing={sorted(expected - features.keys())}, extra={sorted(features.keys() - expected)}"
        )
    transformer = Transformer.from_crs(4326, EQUAL_AREA_CRS, always_xy=True)
    projected: dict[str, Geometry] = {}
    for key, feature in features.items():
        district = DistrictId.model_validate(feature["properties"])
        if feature.get("type") != "Feature" or district.fact_key != key:
            raise ValueError(f"export identity mismatch: {key}")
        # Validate WGS84 structural/range constraints before projecting.
        try:
            TypeAdapter(InputPolygon | InputMultiPolygon).validate_python(feature["geometry"])
        except ValidationError as exc:
            raise ValueError(f"invalid geometry: {key}: {exc}") from exc
        projected[key] = _geometry(feature["geometry"], transformer)
    tiger = load_tiger_archive(sldl, "house") | load_tiger_archive(sldu, "senate")
    print(
        f"CRS={EQUAL_AREA_CRS}; method=100*intersection/union; shortfall in percentage points",
        file=stream,
    )
    results = [Agreement(key, _agreement(projected[key], tiger[key])) for key in sorted(expected)]
    for result in results:
        archive = sldl if result.key.startswith("house:") else sldu
        code = "sldl" if result.key.startswith("house:") else "sldu"
        source = f"https://www2.census.gov/geo/tiger/TIGER2022/{code.upper()}/tl_2022_15_{code}.zip"
        status = "BELOW 99%" if result.agreement < 99 else "OK"
        print(
            f"{result.key}: agreement={result.agreement!r}%; {status}; shortfall={result.shortfall!r} pp; "
            f"export={exported} source={provenance.source_url} vintage={provenance.vintage} "
            f"retrieved={provenance.retrieved_on} method={provenance.method}; "
            f"Census TIGER/Line 2022 source={source} archive={archive}",
            file=stream,
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exported", type=Path)
    parser.add_argument("sldl", type=Path)
    parser.add_argument("sldu", type=Path)
    args = parser.parse_args()
    try:
        results = compare_export(args.exported, args.sldl, args.sldu)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        BadZipFile,
        ProjError,
        shapefile.ShapefileException,
    ) as exc:
        parser.exit(1, f"Overlay failed: {exc}\n")
    parser.exit(1 if any(result.agreement < 99 for result in results) else 0)


if __name__ == "__main__":
    main()
