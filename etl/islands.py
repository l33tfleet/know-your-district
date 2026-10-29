"""Named islands, reviewed district membership and optional official coastlines.

Sole writer of data/geo/islands/ (uv run python -m etl.islands); district exports are only
read. --coastline-dir replays an unmodified Hawaiʻi Statewide GIS Program coastline layer
(coastline.geojson, outSR=4326) with coastline.source.json; without it every island records
coastline "unavailable" with a reason and no geometry. County polygons are never used.
"""

import argparse
import json
from datetime import date
from itertools import batched
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from etl.boundaries import DistrictId, MultiPolygon, Polygon, Provenance

IslandId = Literal["hawaii", "maui", "kahoolawe", "lanai", "molokai", "oahu", "kauai", "niihau"]
# Name, then a reference extent (west, east, south, north; WGS84) drawn in the channels
# between islands. Extents classify polygon parts only and are never published.
ISLANDS: dict[str, tuple[str, tuple[float, float, float, float]]] = {
    "hawaii": ("Hawaiʻi Island", (-156.10, -154.75, 18.85, 20.30)),
    "maui": ("Maui", (-156.70, -155.95, 20.56, 21.035)),
    "kahoolawe": ("Kahoʻolawe", (-156.72, -156.52, 20.48, 20.61)),
    "lanai": ("Lānaʻi", (-157.10, -156.78, 20.70, 20.95)),
    "molokai": ("Molokaʻi", (-157.35, -156.68, 21.04, 21.25)),
    "oahu": ("Oʻahu", (-158.35, -157.60, 21.20, 21.75)),
    "kauai": ("Kauaʻi", (-159.85, -159.25, 21.80, 22.30)),
    "niihau": ("Niʻihau", (-160.30, -160.00, 21.70, 22.10)),
}
MAUI_NUI = ["maui", "kahoolawe", "lanai", "molokai"]
# Reviewed against the 2022 plan: Maui Nui and Kauaʻi–Niʻihau are the multi-island districts.
REVIEWED: dict[str, list[str]] = (
    {f"house-{n:02d}": ["hawaii"] for n in range(1, 9)}
    | {f"house-{n:02d}": ["maui"] for n in (9, 10, 11, 12, 14)}
    | {"house-13": MAUI_NUI, "house-15": ["kauai"], "house-16": ["kauai"]}
    | {"house-17": ["kauai", "niihau"]}
    | {f"house-{n:02d}": ["oahu"] for n in range(18, 52)}
    | {f"senate-{n:02d}": ["hawaii"] for n in range(1, 5)}
    | {"senate-05": ["maui"], "senate-06": ["maui"], "senate-07": MAUI_NUI}
    | {"senate-08": ["kauai", "niihau"]}
    | {f"senate-{n:02d}": ["oahu"] for n in range(9, 26)}
)
NOT_RETRIEVED = (
    "No official coastline: the Hawaiʻi Statewide GIS Program coastline layer was not "
    "retrieved and verified for this import. No geometry is substituted (never county "
    "polygons); render the district silhouette."
)
NOT_IN_LAYER = "The replayed coastline layer has no polygon in this island's extent."
METHODS = {
    "membership_method": "Each part of the State 2022 district layers is assigned to the one "
    "island whose reference extent (etl/islands.py) contains it; the result must equal the "
    "reviewed list. No county polygons are used.",
    "coastline_method": "Replayed unmodified; parts are assigned the same way, parts outside "
    "every extent (Northwestern Hawaiian Islands) are dropped; no simplification.",
    "name_authority": "Hawaiʻi Board on Geographic Names (HRS chapter 4E)",
}
Shape = Annotated[Polygon | MultiPolygon, Field(discriminator="type")]
Rings = list[list[tuple[float, float]]]


class CoastlineSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str = Field(pattern=r"^https://(geodata|geoportal)\.hawaii\.gov/\S+$")
    layer_id: int = Field(ge=0, strict=True)
    retrieved_on: date
    credit: str = Field(min_length=1)


class Available(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available"]
    source: CoastlineSource


class Unavailable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unavailable"]
    reason: str = Field(min_length=20)


class Island(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: IslandId
    name: str
    coastline: Annotated[Available | Unavailable, Field(discriminator="status")]

    @model_validator(mode="after")
    def canonical_name(self) -> Self:
        if self.name != ISLANDS[self.id][0]:
            raise ValueError(f"{self.id} must be named {ISLANDS[self.id][0]!r}")
        return self


class IslandsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provenance: dict[str, str | list[Provenance]]
    islands: list[Island]

    @model_validator(mode="after")
    def every_island_once(self) -> Self:
        if [island.id for island in self.islands] != list(ISLANDS):
            raise ValueError(f"islands must be exactly {list(ISLANDS)} in order")
        return self


class _District(BaseModel):
    properties: DistrictId
    geometry: Shape


class _Part(BaseModel):
    geometry: Shape


class _Collection[F: BaseModel](BaseModel):
    type: Literal["FeatureCollection"]
    features: list[F]
    properties: dict[str, object] = {}
    exceeded_transfer_limit: bool = Field(default=False, alias="exceededTransferLimit")


def classify(geometry: Shape, *, required: bool = True) -> list[tuple[str | None, Rings]]:
    """Each part with the island whose extent holds it (None: optional, touches no extent)."""
    result: list[tuple[str | None, Rings]] = []
    parts = [geometry.coordinates] if isinstance(geometry, Polygon) else geometry.coordinates
    for rings in parts:
        xs, ys = [x for ring in rings for x, _ in ring], [y for ring in rings for _, y in ring]
        w, e, s, n = min(xs), max(xs), min(ys), max(ys)
        box = [(i, extent) for i, (_, extent) in ISLANDS.items()]
        inside = [i for i, (bw, be, bs, bn) in box if bw <= w and e <= be and bs <= s and n <= bn]
        touch = any(w <= be and bw <= e and s <= bn and bs <= n for _, (bw, be, bs, bn) in box)
        if len(inside) != 1 and (touch or required):
            raise ValueError(f"part {w, e, s, n} is not within exactly one island extent")
        result.append((inside[0] if inside else None, rings))
    return result


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_islands(geo_dir: Path, output_dir: Path, coastline_dir: Path | None = None) -> None:
    """Validate every input first, then write islands/; district files are only read."""
    found: dict[str, set[str | None]] = {}
    sources: list[Provenance] = []
    credits: list[str] = []
    for chamber in ("house", "senate"):
        stem = geo_dir / chamber
        sources.append(Provenance.model_validate_json(_read(stem.with_suffix(".provenance.json"))))
        credits.append(_read(stem.with_suffix(".credit.txt")).strip())
        layer = _Collection[_District].model_validate_json(_read(stem.with_suffix(".geojson")))
        for feature in layer.features:
            key = feature.properties.key
            try:
                found.setdefault(key, set()).update(i for i, _ in classify(feature.geometry))
            except ValueError as exc:
                raise ValueError(f"{key}: {exc}") from None
    membership = {key: [i for i in ISLANDS if i in found[key]] for key in sorted(found)}
    keys = membership.keys() | REVIEWED.keys()
    if wrong := sorted(k for k in keys if membership.get(k) != REVIEWED.get(k)):
        raise ValueError(f"membership differs from the reviewed list: {wrong}")
    source: CoastlineSource | None = None
    shapes: dict[str, list[Rings]] = {}
    if coastline_dir:
        source = CoastlineSource.model_validate_json(_read(coastline_dir / "coastline.source.json"))
        layer = _Collection[_Part].model_validate_json(_read(coastline_dir / "coastline.geojson"))
        # ArcGIS reports truncation at the top level or inside the collection's properties.
        if layer.exceeded_transfer_limit or layer.properties.get("exceededTransferLimit"):
            raise ValueError("incomplete response: exceededTransferLimit")
        for feature in layer.features:
            for island, rings in classify(feature.geometry, required=False):
                if island:
                    shapes.setdefault(island, []).append(rings)
        credits.append(source.credit)
    unavailable = {"status": "unavailable", "reason": NOT_IN_LAYER if source else NOT_RETRIEVED}
    islands = [
        {"id": island, "name": name, "coastline": unavailable}
        | ({"coastline": {"status": "available", "source": source}} if island in shapes else {})
        for island, (name, _) in ISLANDS.items()
    ]
    provenance = METHODS | {"district_sources": sources}
    document = IslandsDocument.model_validate({"provenance": provenance, "islands": islands})
    dump = document.model_dump(mode="json")
    # Compact rows (one island, six districts or one coastline per line) keep diffs reviewable.
    rows = ",\n    ".join(_compact(island) for island in dump["islands"])
    text = f'{{\n  "provenance": {_compact(dump["provenance"])},\n  "islands": [\n    {rows}\n  ]\n}}\n'
    pairs = [f"{_compact(key)}: {_compact(value)}" for key, value in membership.items()]
    districts = "{\n  " + ",\n  ".join(", ".join(row) for row in batched(pairs, 6)) + "\n}\n"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "islands.json").write_text(text, "utf-8")
    (output_dir / "membership.json").write_text(districts, "utf-8")
    (output_dir / "credit.txt").write_text("\n".join(credits) + "\n", "utf-8")
    path = output_dir / "coastlines.geojson"
    path.unlink(missing_ok=True)
    if shapes:
        multi = {
            i: {"type": "MultiPolygon", "coordinates": shapes[i]} for i in ISLANDS if i in shapes
        }
        features = [
            {"type": "Feature", "properties": {"island": i}, "geometry": g}
            for i, g in multi.items()
        ]
        path.write_text(
            _compact({"type": "FeatureCollection", "features": features}) + "\n", "utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geo-dir", type=Path, default=Path("data/geo"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/geo/islands"))
    parser.add_argument("--coastline-dir", type=Path)
    args = parser.parse_args()
    try:
        build_islands(args.geo_dir, args.output_dir, args.coastline_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Island build failed: {exc}\n")
    print(f"Published islands and membership for 76 districts to {args.output_dir}")


if __name__ == "__main__":
    main()
