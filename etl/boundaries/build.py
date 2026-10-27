"""Rebuild State district shapes, TIGER evidence and a required read-only fact join.

Offline replay: --source-dir contains state-house.json, state-senate.json and
Census tl_2022_15_sldl.zip / tl_2022_15_sldu.zip downloaded without modification.
No synthetic fact database is substituted when #24's database is unavailable.
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import BadZipFile

from pyproj import Transformer
from pyproj.exceptions import ProjError

from etl.boundaries import BoundaryCollection, Polygon
from etl.boundaries.overlay import (
    EQUAL_AREA_CRS,
    agreement,
    load_tiger_archive,
    shapefile,
)
from etl.boundaries.production import compare_fact_keys, export_boundaries, fact_key
from etl.boundaries.state import LAYERS, Chamber, StateBoundary, fetch_state_boundary


def build_boundaries(output_dir: Path, facts_db: Path, source_dir: Path | None = None) -> None:
    """Publish both chambers and all evidence; fail if the fact join is unproved."""
    names = [
        f"{chamber}{suffix}"
        for chamber in LAYERS
        for suffix in (".geojson", ".provenance.json", ".credit.txt")
    ] + ["overlay.md", "mismatch.md", "fact-keys.md"]
    destinations = {(output_dir / name).resolve() for name in names}
    if len(destinations) != len(names) or facts_db.resolve() in destinations:
        raise ValueError("output paths must be distinct from each other and the fact database")
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="boundaries-") as temporary:
        stage = Path(temporary)
        chambers: dict[Chamber, StateBoundary] = {}
        for chamber in LAYERS:
            if source_dir is None:
                boundary = fetch_state_boundary(chamber)
            else:
                payload: object = json.loads(
                    (source_dir / f"state-{chamber}.json").read_text(encoding="utf-8")
                )
                boundary = fetch_state_boundary(
                    chamber, get_json=lambda _url, payload=payload: payload
                )
            chambers[chamber] = boundary
        collection = BoundaryCollection(
            type="FeatureCollection",
            provenance=chambers["house"].collection.provenance,
            features=[
                feature for item in chambers.values() for feature in item.collection.features
            ],
        )
        combined = stage / "districts.geojson"
        export_boundaries(
            collection, combined, credit="; ".join(item.credit for item in chambers.values())
        )
        exported = json.loads(combined.read_text(encoding="utf-8"))
        for chamber, boundary in chambers.items():
            document = {
                "type": "FeatureCollection",
                "features": [
                    feature
                    for feature in exported["features"]
                    if feature["properties"]["chamber"] == chamber
                ],
            }
            path = stage / f"{chamber}.geojson"
            path.write_text(
                json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            path.with_suffix(".provenance.json").write_text(
                boundary.collection.provenance.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            path.with_suffix(".credit.txt").write_text(boundary.credit + "\n", encoding="utf-8")
        archives: list[Path] = []
        for code in ("sldl", "sldu"):
            name = f"tl_2022_15_{code}.zip"
            archive = stage / name
            if source_dir is None:
                url = f"https://www2.census.gov/geo/tiger/TIGER2022/{code.upper()}/{name}"
                with urlopen(url, timeout=120) as response:
                    archive.write_bytes(response.read())
            else:
                shutil.copyfile(source_dir / name, archive)
            archives.append(archive)
        transformer = Transformer.from_crs(4326, EQUAL_AREA_CRS, always_xy=True)
        lines = [
            f"CRS={EQUAL_AREA_CRS}; method=100*intersection/union; shortfall in percentage points"
        ]
        for (chamber, boundary), archive in zip(chambers.items(), archives, strict=True):
            tiger = load_tiger_archive(archive, chamber)
            code = "sldl" if chamber == "house" else "sldu"
            source = f"https://www2.census.gov/geo/tiger/TIGER2022/{code.upper()}/{archive.name}"
            for feature in boundary.collection.features:
                key = fact_key(feature.properties)
                polygons = (
                    [feature.geometry.coordinates]
                    if isinstance(feature.geometry, Polygon)
                    else feature.geometry.coordinates
                )
                projected = {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [transformer.transform(x, y, errcheck=True) for x, y in ring]
                            for ring in polygon
                        ]
                        for polygon in polygons
                    ],
                }
                try:
                    value = agreement(
                        projected, {"type": "MultiPolygon", "coordinates": tiger[key]}
                    )
                except ValueError as exc:
                    status = f"UNVERIFIED: {exc}; agreement unavailable; no repair performed"
                else:
                    flag = "BELOW 99%" if value < 99 else "OK"
                    status = f"agreement={value!r}%; {flag}; shortfall={max(0, 99 - value)!r} pp"
                provenance = boundary.collection.provenance
                lines.append(
                    f"{key}: {status}; displayed=State of Hawaiʻi; "
                    f"source={provenance.source_url}; retrieved={provenance.retrieved_on}; "
                    f"vintage={provenance.vintage}; method={provenance.method}; TIGER source={source}"
                )
        report = "\n".join(lines) + "\n"
        (stage / "overlay.md").write_text(
            "# State / Census TIGER overlay\n\nDisplayed geometry: State of Hawaiʻi 2022 plan.\n"
            "Agreement is area intersection / union; no geometry is replaced by TIGER.\n\n"
            "```text\n" + report + "```\n",
            encoding="utf-8",
        )
        below = [
            line for line in report.splitlines() if "BELOW 99%" in line or "UNVERIFIED" in line
        ]
        (stage / "mismatch.md").write_text(
            "# Overlay mismatches\n\nDisplayed source: State of Hawaiʻi; see chamber provenance "
            "and credit sidecars. All district results and method are in overlay.md.\n\n"
            + (
                "```text\n" + "\n".join(below) + "\n```\n"
                if below
                else "No districts below 99%. All overlays verified.\n"
            ),
            encoding="utf-8",
        )
        failure: str | None = None
        try:
            compare_fact_keys(
                facts_db, {fact_key(feature.properties) for feature in collection.features}
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            failure = f"Join unavailable or failed; #24 must deliver the real fact database: {exc}"
            proof = failure
        else:
            digest = hashlib.sha256(facts_db.read_bytes()).hexdigest()
            proof = f"PASS: exact House and Senate fact-key equality; missing=[]; extra=[]; sha256={digest}"
        (stage / "fact-keys.md").write_text(
            f"# Fact geography join\n\nDatabase: {facts_db}\n\n{proof}\n"
            "\nMethod: SELECT DISTINCT geography FROM facts, read-only; exclude state:15 and "
            "county keys, translate district IDs to WO59 qualified keys, compare both directions. "
            "Key equality does not prove fact completeness or geographic correspondence.\n",
            encoding="utf-8",
        )
        for artifact in stage.iterdir():
            if artifact.name.startswith(("house.", "senate.")) or artifact.suffix == ".md":
                shutil.copyfile(artifact, output_dir / artifact.name)
        print(
            f"Published both State chambers, {len(collection.features)} overlays and join evidence to {output_dir}"
        )
        if failure is not None:
            raise ValueError(failure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/geo"))
    parser.add_argument("--facts-db", type=Path, default=Path("data/facts.sqlite"))
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    try:
        build_boundaries(args.output_dir, args.facts_db, args.source_dir)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        sqlite3.Error,
        BadZipFile,
        ProjError,
        shapefile.ShapefileException,
    ) as exc:
        parser.exit(1, f"Boundary build failed: {exc}\n")


if __name__ == "__main__":
    main()
