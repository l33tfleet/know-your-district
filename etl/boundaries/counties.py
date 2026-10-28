"""Offline State district / TIGER 2022 county overlay, using the #93 equal-area engine.

uv run python -m etl.boundaries.counties HOUSE.geojson SENATE.geojson COUNTY.zip OUTPUT.tsv
Inputs are production exports (including provenance and credit sidecars) and
https://www2.census.gov/geo/tiger/TIGER2022/COUNTY/tl_2022_us_county.zip.
Only configured counties participate: Kalawao remains excluded. Shares use
county-covered district area, excluding water/coastline differences between sources.
No sliver threshold, snapping, buffering or geometry repair is applied.
"""

import argparse
import csv
import hashlib
import io
import json
import tomllib
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from pydantic import TypeAdapter
from pyproj import CRS, Transformer

from app.counties import CountyShare, load_mapping
from etl.boundaries import BoundaryCollection, Provenance, expected_fact_keys
from etl.boundaries.overlay import (
    EQUAL_AREA_CRS,
    Geometry,
    areas,
    shapefile,
    shapefile_geometry,
)
from etl.boundaries.overlay import (
    geometry as project_geometry,
)

COUNTY_SOURCE = "https://www2.census.gov/geo/tiger/TIGER2022/COUNTY/tl_2022_us_county.zip"
METHOD = (
    "EPSG:6933 equal-area polygon intersection; share = county intersection area / "
    "sum of configured county intersection areas; Kalawao excluded; "
    "water/coastline differences excluded from denominator; no sliver threshold or repair."
)


def area_shares(district: object, counties: dict[str, object]) -> dict[str, float]:
    """Shares for already projected polygons, retaining every positive intersection."""
    return _shares(
        project_geometry(district), {code: project_geometry(g) for code, g in counties.items()}
    )


def _shares(district: Geometry, counties: dict[str, Geometry]) -> dict[str, float]:
    overlaps = {code: areas(district, geometry)[2] for code, geometry in counties.items()}
    total = sum(overlaps.values())
    if total <= 0:
        raise ValueError("no county overlap")
    return {code: area / total for code, area in overlaps.items() if area > 0}


def load_counties(path: Path) -> dict[str, Geometry]:
    config = tomllib.loads((Path(__file__).resolve().parents[2] / "config.toml").read_text())
    codes = set(config["acs"]["county_codes"])
    result: dict[str, Geometry] = {}
    with ZipFile(path) as archive:
        names = archive.namelist()
        shapes = [name for name in names if name.endswith(".shp")]
        if len(shapes) != 1:
            raise ValueError("county archive requires exactly one shapefile")
        stem = shapes[0][:-4]
        members = [stem + suffix for suffix in (".shp", ".shx", ".dbf", ".prj")]
        if any(names.count(member) != 1 for member in members):
            raise ValueError("county archive requires matching .shp/.shx/.dbf/.prj")
        transformer = Transformer.from_crs(
            CRS.from_wkt(archive.read(members[3]).decode()), EQUAL_AREA_CRS, always_xy=True
        )
        with shapefile.Reader(
            shp=io.BytesIO(archive.read(members[0])),
            shx=io.BytesIO(archive.read(members[1])),
            dbf=io.BytesIO(archive.read(members[2])),
        ) as reader:
            for record in reader.iterShapeRecords():
                attributes: dict[str, Any] = record.record.as_dict()
                if attributes["STATEFP"] != "15" or attributes["COUNTYFP"] not in codes:
                    continue
                code = str(attributes["COUNTYFP"])
                if attributes["GEOID"] != "15" + code:
                    raise ValueError("county GEOID mismatch")
                if code in result:
                    raise ValueError(f"duplicate county: {code}")
                result[code] = project_geometry(shapefile_geometry(record.shape), transformer)
    if result.keys() != codes:
        raise ValueError("county set mismatch")
    return result


def build_mapping(house: Path, senate: Path, county: Path, output: Path) -> None:
    county_shapes = load_counties(county)
    rows: list[CountyShare] = []
    sources: list[dict[str, object]] = []
    transformer = Transformer.from_crs(4326, EQUAL_AREA_CRS, always_xy=True)
    for path in (house, senate):
        document = TypeAdapter(dict[str, Any]).validate_json(path.read_text())
        provenance = Provenance.model_validate_json(
            path.with_suffix(".provenance.json").read_text()
        )
        features = document["features"]
        normalized = [{k: v for k, v in feature.items() if k != "id"} for feature in features]
        collection = BoundaryCollection.model_validate(
            document | {"features": normalized, "provenance": provenance.model_dump(mode="json")}
        )
        if any(
            source["id"] != feature.properties.fact_key
            for source, feature in zip(features, collection.features, strict=True)
        ):
            raise ValueError("export identity mismatch")
        sources.append(
            {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "provenance": provenance.model_dump(mode="json"),
                "credit": path.with_suffix(".credit.txt").read_text().strip(),
            }
        )
        for feature in collection.features:
            geometry = project_geometry(feature.geometry.model_dump(mode="json"), transformer)
            for code, share in _shares(geometry, county_shapes).items():
                rows.append(
                    CountyShare(
                        district=feature.properties.fact_key,
                        county=f"county:15:{code}",
                        area_share=share,
                        district_source=str(provenance.source_url),
                        county_source=COUNTY_SOURCE,
                        vintage="2022 district plan; TIGER/Line 2022 counties",
                        method=METHOD,
                    )
                )
    if {r.district for r in rows} != expected_fact_keys():
        raise ValueError("district set mismatch")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(CountyShare.model_fields), delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(r.model_dump() for r in sorted(rows, key=lambda r: (r.district, r.county)))
    output.write_text(buffer.getvalue(), encoding="utf-8")
    load_mapping(output)
    output.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                "district_sources": sources,
                "county_source": COUNTY_SOURCE,
                "county_sha256": hashlib.sha256(county.read_bytes()).hexdigest(),
                "method": METHOD,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("house", "senate", "county", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    build_mapping(args.house, args.senate, args.county, args.output)


if __name__ == "__main__":
    main()
