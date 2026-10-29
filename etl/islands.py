"""Named islands, reviewed district membership and optional official coastlines.

uv run python -m etl.islands [--geo-dir data/geo] [--output-dir data/geo/islands]
                             [--coastline-dir DIR]

Sole writer of data/geo/islands/. Reads the committed State district exports
(house/senate .geojson, .provenance.json, .credit.txt) and never writes them.
Each district polygon part is assigned to the one island whose reference extent
contains the part's bounding box; a district lists every island it touches, and
the result must equal REVIEWED. No county polygons are used for islands.

Coastlines are optional. Offline replay: DIR holds coastline.geojson (the
Hawaiʻi Statewide GIS Program layer queried with f=geojson&outSR=4326, unmodified)
and coastline.source.json (service_url, layer_id, retrieved_on, credit). Without
DIR every island records coastline "unavailable" with a reason and no geometry,
so consumers render the district silhouette instead.
"""

import argparse
import json
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, HttpUrl, TypeAdapter
from pydantic.functional_validators import field_validator, model_validator

from etl.boundaries import Chamber, DistrictId, MultiPolygon, Polygon, Provenance

IslandId = Literal["hawaii", "maui", "kahoolawe", "lanai", "molokai", "oahu", "kauai", "niihau"]
ISLANDS: dict[str, str] = {
    "hawaii": "Hawaiʻi Island",
    "maui": "Maui",
    "kahoolawe": "Kahoʻolawe",
    "lanai": "Lānaʻi",
    "molokai": "Molokaʻi",
    "oahu": "Oʻahu",
    "kauai": "Kauaʻi",
    "niihau": "Niʻihau",
}
# Reference extents (west, east, south, north; WGS84 degrees) drawn in the channels
# between islands. They classify parts only and are never published as geometry.
EXTENTS: dict[str, tuple[float, float, float, float]] = {
    "hawaii": (-156.10, -154.75, 18.85, 20.30),
    "maui": (-156.70, -155.95, 20.56, 21.035),
    "kahoolawe": (-156.72, -156.52, 20.48, 20.61),
    "lanai": (-157.10, -156.78, 20.70, 20.95),
    "molokai": (-157.35, -156.68, 21.04, 21.25),
    "oahu": (-158.35, -157.60, 21.20, 21.75),
    "kauai": (-159.85, -159.25, 21.80, 22.30),
    "niihau": (-160.30, -160.00, 21.70, 22.10),
}
MAUI_NUI = ("maui", "kahoolawe", "lanai", "molokai")
# Reviewed against the 2022 plan: Maui Nui and Kauaʻi–Niʻihau are the multi-island districts.
REVIEWED: Mapping[str, tuple[str, ...]] = (
    {f"house-{n:02d}": ("hawaii",) for n in range(1, 9)}
    | {f"house-{n:02d}": ("maui",) for n in (9, 10, 11, 12, 14)}
    | {"house-13": MAUI_NUI, "house-15": ("kauai",), "house-16": ("kauai",)}
    | {"house-17": ("kauai", "niihau")}
    | {f"house-{n:02d}": ("oahu",) for n in range(18, 52)}
    | {f"senate-{n:02d}": ("hawaii",) for n in range(1, 5)}
    | {"senate-05": ("maui",), "senate-06": ("maui",), "senate-07": MAUI_NUI}
    | {"senate-08": ("kauai", "niihau")}
    | {f"senate-{n:02d}": ("oahu",) for n in range(9, 26)}
)
COASTLINE_HOSTS = {"geodata.hawaii.gov", "geoportal.hawaii.gov"}
MEMBERSHIP_METHOD = (
    "Each polygon part of the State 2022 district layer is assigned to the one island whose "
    "reference extent (etl/islands.py EXTENTS) contains the part's bounding box; a district "
    "lists every island it touches; the result must equal the reviewed list. "
    "No county polygons are used."
)
COASTLINE_METHOD = (
    "Replayed unmodified GeoJSON (outSR=4326); each polygon part is assigned to the one island "
    "whose reference extent contains its bounding box; parts outside every extent "
    "(e.g. Northwestern Hawaiian Islands) are dropped; no simplification or repair."
)
NOT_RETRIEVED = (
    "No official coastline: the Hawaiʻi Statewide GIS Program coastline layer was not "
    "retrieved and verified for this import, so no service URL, layer ID or retrieval date "
    "is recorded. No geometry is substituted (never county polygons); render the district "
    "silhouette."
)
NOT_IN_LAYER = (
    "The replayed Hawaiʻi Statewide GIS Program coastline layer has no polygon within this "
    "island's reference extent. No geometry is substituted; render the district silhouette."
)
NAME_AUTHORITY = "Hawaiʻi Board on Geographic Names (HRS chapter 4E)"
NAME_BASIS = "Spellings carry the ʻokina (U+02BB) and kahakō (AGENTS.md rule 6)."


def _iso_date(value: object) -> object:
    if isinstance(value, str) and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("retrieved_on must be an ISO calendar date (YYYY-MM-DD)")
    return value


IsoDate = Annotated[date, BeforeValidator(_iso_date)]
Shape = Annotated[Polygon | MultiPolygon, Field(discriminator="type")]
Parts = list[list[list[tuple[float, float]]]]


class CoastlineSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: HttpUrl
    layer_id: int = Field(ge=0, strict=True)
    retrieved_on: IsoDate
    credit: str = Field(min_length=1)
    method: str = Field(min_length=1)

    @field_validator("service_url")
    @classmethod
    def official_host(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.host not in COASTLINE_HOSTS:
            raise ValueError(f"coastline must come over https from {sorted(COASTLINE_HOSTS)}")
        return value


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
        if self.name != ISLANDS[self.id]:
            raise ValueError(f"{self.id} must be named {ISLANDS[self.id]!r}")
        return self


class DistrictSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chamber: Chamber
    source_url: HttpUrl
    retrieved_on: IsoDate
    credit: str = Field(min_length=1)


class IslandProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    membership_method: str = Field(min_length=1)
    district_sources: list[DistrictSource] = Field(min_length=2, max_length=2)
    name_authority: str = Field(min_length=1)
    name_basis: str = Field(min_length=1)
    names_verified_online: bool


class IslandsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provenance: IslandProvenance
    islands: list[Island]

    @model_validator(mode="after")
    def every_island_once(self) -> Self:
        if [island.id for island in self.islands] != list(ISLANDS):
            raise ValueError(f"islands must be exactly {list(ISLANDS)} in order")
        return self


class Membership(BaseModel):
    model_config = ConfigDict(extra="forbid")
    districts: dict[str, list[IslandId]]

    @model_validator(mode="after")
    def reviewed(self) -> Self:
        actual: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in self.districts.items()}
        keys = actual.keys() | REVIEWED.keys()
        if wrong := sorted(k for k in keys if actual.get(k) != REVIEWED.get(k)):
            raise ValueError(f"membership differs from the reviewed list: {wrong}")
        return self


class CoastlineFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    properties: dict[Literal["island"], IslandId]
    geometry: MultiPolygon


class Coastlines(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"]
    features: list[CoastlineFeature]


class _DistrictFeature(BaseModel):
    """One feature of a production district export (etl/boundaries/build.py)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    id: str
    properties: DistrictId
    geometry: Shape


class _SourceFeature(BaseModel):
    type: Literal["Feature"]
    geometry: Shape


class _SourceCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[_SourceFeature]
    properties: dict[str, object] = Field(default_factory=dict)
    exceeded_transfer_limit: bool = Field(default=False, alias="exceededTransferLimit")


class IslandData(BaseModel):
    islands: list[Island]
    membership: dict[str, list[str]]
    coastlines: dict[str, MultiPolygon]


def classify(rings: list[list[tuple[float, float]]], *, required: bool = True) -> str | None:
    """The island whose extent contains this part; None if optional and outside every extent."""
    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    west, east, south, north = min(xs), max(xs), min(ys), max(ys)
    boxes = EXTENTS.items()
    inside = [
        i for i, (w, e, s, n) in boxes if w <= west and east <= e and s <= south <= north <= n
    ]
    touched = [
        i for i, (w, e, s, n) in boxes if west <= e and w <= east and south <= n and s <= north
    ]
    if len(inside) == 1:
        return inside[0]
    if not touched and not required:
        return None
    raise ValueError(f"part {west, east, south, north} is not within exactly one island extent")


def _parts(geometry: Polygon | MultiPolygon) -> Parts:
    return [geometry.coordinates] if isinstance(geometry, Polygon) else geometry.coordinates


def derive_membership(geo_dir: Path) -> tuple[dict[str, list[str]], list[DistrictSource]]:
    membership: dict[str, list[str]] = {}
    sources: list[DistrictSource] = []
    for chamber in ("house", "senate"):
        stem = geo_dir / chamber
        document = json.loads(stem.with_suffix(".geojson").read_text(encoding="utf-8"))
        features = TypeAdapter(list[_DistrictFeature]).validate_python(document["features"])
        provenance = Provenance.model_validate_json(
            stem.with_suffix(".provenance.json").read_text(encoding="utf-8")
        )
        sources.append(
            DistrictSource(
                chamber=chamber,
                source_url=provenance.source_url,
                retrieved_on=provenance.retrieved_on,
                credit=stem.with_suffix(".credit.txt").read_text(encoding="utf-8").strip(),
            )
        )
        for feature in features:
            key = feature.properties.key
            if feature.id != feature.properties.fact_key or key in membership:
                raise ValueError(f"{key}: duplicate or mismatched feature id {feature.id!r}")
            try:
                found = {classify(part) for part in _parts(feature.geometry)}
            except ValueError as exc:
                raise ValueError(f"{key}: {exc}") from None
            membership[key] = [island for island in ISLANDS if island in found]
    return dict(sorted(membership.items())), sources


def replay_coastline(source_dir: Path) -> tuple[CoastlineSource, dict[str, MultiPolygon]]:
    meta = TypeAdapter(dict[str, object]).validate_json(
        (source_dir / "coastline.source.json").read_text(encoding="utf-8")
    )
    source = CoastlineSource.model_validate(meta | {"method": COASTLINE_METHOD})
    collection = _SourceCollection.model_validate_json(
        (source_dir / "coastline.geojson").read_text(encoding="utf-8")
    )
    # ArcGIS GeoJSON may also put transfer-limit information in foreign properties.
    if collection.exceeded_transfer_limit or collection.properties.get("exceededTransferLimit"):
        raise ValueError("incomplete response: exceededTransferLimit")
    grouped: dict[str, Parts] = {}
    for feature in collection.features:
        for part in _parts(feature.geometry):
            if (island := classify(part, required=False)) is not None:
                grouped.setdefault(island, []).append(part)
    return source, {
        island: MultiPolygon(type="MultiPolygon", coordinates=grouped[island])
        for island in ISLANDS
        if island in grouped
    }


def _json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def build_islands(geo_dir: Path, output_dir: Path, coastline_dir: Path | None = None) -> None:
    """Validate everything first, then write islands/; district files are only read."""
    membership, sources = derive_membership(geo_dir)
    Membership.model_validate({"districts": membership})
    source, shapes = replay_coastline(coastline_dir) if coastline_dir else (None, {})
    reason = NOT_IN_LAYER if source else NOT_RETRIEVED
    document = IslandsDocument.model_validate(
        {
            "provenance": {
                "membership_method": MEMBERSHIP_METHOD,
                "district_sources": sources,
                "name_authority": NAME_AUTHORITY,
                "name_basis": NAME_BASIS,
                "names_verified_online": False,
            },
            "islands": [
                {
                    "id": island,
                    "name": name,
                    "coastline": {"status": "available", "source": source}
                    if source and island in shapes
                    else {"status": "unavailable", "reason": reason},
                }
                for island, name in ISLANDS.items()
            ],
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "islands.json").write_text(_json(document.model_dump(mode="json")), "utf-8")
    # One district per line keeps the reviewed membership readable in diffs.
    rows = [f"    {json.dumps(key)}: {json.dumps(value)}" for key, value in membership.items()]
    text = "\n".join(["{", '  "districts": {', ",\n".join(rows), "  }", "}", ""])
    (output_dir / "membership.json").write_text(text, "utf-8")
    credits = [item.credit for item in sources] + ([source.credit] if source else [])
    (output_dir / "credit.txt").write_text("\n".join(credits) + "\n", "utf-8")
    path = output_dir / "coastlines.geojson"
    if shapes:
        features = [
            {"type": "Feature", "properties": {"island": island}, "geometry": shape.model_dump()}
            for island, shape in shapes.items()
        ]
        path.write_text(_json({"type": "FeatureCollection", "features": features}), "utf-8")
    else:
        path.unlink(missing_ok=True)


def load_islands(directory: Path = Path("data/geo/islands")) -> IslandData:
    """Validate islands/: names, reviewed membership and coastline availability agree."""
    document = IslandsDocument.model_validate_json(
        (directory / "islands.json").read_text(encoding="utf-8")
    )
    membership = Membership.model_validate_json(
        (directory / "membership.json").read_text(encoding="utf-8")
    )
    available = {i.id for i in document.islands if i.coastline.status == "available"}
    path = directory / "coastlines.geojson"
    coastlines: dict[str, MultiPolygon] = {}
    if available or path.exists():
        for feature in Coastlines.model_validate_json(path.read_text(encoding="utf-8")).features:
            island = feature.properties["island"]
            if island in coastlines:
                raise ValueError(f"duplicate coastline: {island}")
            coastlines[island] = feature.geometry
    if set(coastlines) != available:
        raise ValueError(f"coastline availability mismatch: {sorted(set(coastlines) ^ available)}")
    return IslandData(
        islands=document.islands,
        membership={key: list(value) for key, value in membership.districts.items()},
        coastlines=coastlines,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geo-dir", type=Path, default=Path("data/geo"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/geo/islands"))
    parser.add_argument("--coastline-dir", type=Path)
    args = parser.parse_args()
    try:
        build_islands(args.geo_dir, args.output_dir, args.coastline_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Island build failed: {exc}\n")
    print(f"Published islands and membership for 76 districts to {args.output_dir}")


if __name__ == "__main__":
    main()
