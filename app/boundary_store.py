"""District geometry, island names and attribution by qualified district ID.

Reads the artifacts in data/geo/ (written by etl.boundaries and etl.islands) and checks that
they agree: feature IDs, sidecars and island references. A missing or mismatched reference
raises; an island recorded as coastline "unavailable" is kept, with no geometry, so a consumer
can render the silhouette. Geometry is structurally validated only and exposed as exported:
no topology repair. Loading only reads files.
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from etl.boundaries import (
    DISTRICT_COUNTS,
    Chamber,
    DistrictId,
    MultiPolygon,
    Provenance,
    all_districts,
    expected_fact_keys,
)
from etl.islands import REVIEWED, Available, Island, IslandId, IslandsDocument, Shape, Unavailable

GEO_DIR = Path(__file__).resolve().parents[1] / "data/geo"
Coastline = Annotated[Available | Unavailable, Field(discriminator="status")]
_MEMBERSHIP = TypeAdapter(dict[str, list[IslandId]])


class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    credit: str
    provenance: Provenance
    name_authority: str
    membership_method: str


class IslandBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: IslandId
    name: str
    coastline: Coastline
    geometry: MultiPolygon | None


class DistrictBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    district: DistrictId
    geometry: Shape
    islands: tuple[IslandBoundary, ...]
    attribution: Attribution


class BoundaryStore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    districts: dict[str, DistrictBoundary]

    def district(self, district_id: str) -> DistrictBoundary:
        """The district with this qualified ID, such as house:15:001:2022."""
        if district_id not in self.districts:
            raise ValueError(
                f"unknown district id {district_id!r}; valid ids look like house:15:001:2022"
            )
        return self.districts[district_id]


class _Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    id: str
    properties: DistrictId
    geometry: Shape


class _Layer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"]
    features: list[_Feature]


class _CoastlineProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")
    island: IslandId


class _CoastlineFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    properties: _CoastlineProperties
    geometry: MultiPolygon


class _Coastlines(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"]
    features: list[_CoastlineFeature]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse[M: BaseModel](model: type[M], path: Path) -> M:
    try:
        return model.model_validate_json(_read(path))
    except ValidationError as exc:
        raise ValueError(f"{path}: {exc}") from None


def _credit(path: Path) -> str:
    line = _read(path).removesuffix("\n")
    if not re.fullmatch(r"\S[^\x00-\x1f]*", line):
        raise ValueError(f"{path}: credit must be one line of text")
    return line


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    repeated = [key for key, count in Counter(key for key, _ in pairs).items() if count > 1]
    if repeated:
        raise ValueError(f"duplicate keys: {repeated}")
    return dict(pairs)


def _layer(path: Path, chamber: Chamber) -> dict[str, _Feature]:
    features = _parse(_Layer, path).features
    for feature in features:
        if feature.id != feature.properties.fact_key:
            raise ValueError(
                f"{path}: feature id {feature.id} does not match {feature.properties.fact_key}"
            )
    counts = Counter(feature.id for feature in features)
    if repeated := sorted(key for key, count in counts.items() if count > 1):
        raise ValueError(f"{path}: duplicate feature ids: {repeated}")
    expected = expected_fact_keys(chamber)
    if counts.keys() != expected:
        raise ValueError(
            f"{path}: missing={sorted(expected - counts.keys())}, "
            f"unexpected={sorted(counts.keys() - expected)}"
        )
    return {feature.id: feature for feature in features}


def _membership(path: Path) -> dict[str, list[IslandId]]:
    try:
        raw = json.loads(_read(path), object_pairs_hook=_unique_keys)
        membership = _MEMBERSHIP.validate_python(raw)
    except ValueError as exc:  # JSONDecodeError and ValidationError are ValueErrors
        raise ValueError(f"{path}: {exc}") from None
    missing = sorted(REVIEWED.keys() - membership.keys())
    unexpected = sorted(membership.keys() - REVIEWED.keys())
    shared = membership.keys() & REVIEWED.keys()
    mismatched = sorted(key for key in shared if membership[key] != REVIEWED[key])
    if missing or unexpected or mismatched:
        raise ValueError(f"{path}: {missing=}, {unexpected=}, {mismatched=}")
    return membership


def _coastlines(path: Path, islands: list[Island]) -> dict[str, MultiPolygon]:
    features = _parse(_Coastlines, path).features if path.exists() else []
    counts = Counter(feature.properties.island for feature in features)
    if repeated := [island for island, count in counts.items() if count > 1]:
        raise ValueError(f"{path}: duplicate coastline features: {repeated}")
    available = {island.id for island in islands if island.coastline.status == "available"}
    if extra := sorted(counts.keys() - available):
        raise ValueError(f"{path}: coastline geometry for unavailable islands: {extra}")
    if absent := sorted(available - counts.keys()):
        raise ValueError(f"{path}: no coastline geometry for available islands: {absent}")
    return {feature.properties.island: feature.geometry for feature in features}


def load_boundaries(geo_dir: Path | None = None) -> BoundaryStore:
    """Read and cross-check every artifact; raise naming the first file that disagrees."""
    geo = geo_dir or GEO_DIR
    document = _parse(IslandsDocument, geo / "islands/islands.json")
    layers = {c: _layer(geo / f"{c}.geojson", c) for c in DISTRICT_COUNTS}
    sources = {c: _parse(Provenance, geo / f"{c}.provenance.json") for c in DISTRICT_COUNTS}
    credits = {c: _credit(geo / f"{c}.credit.txt") for c in DISTRICT_COUNTS}
    if document.provenance.district_sources != list(sources.values()):
        raise ValueError(f"{geo}: district provenance sidecars do not match islands.json")
    coastline_credits = [
        island.coastline.source.credit
        for island in document.islands
        if island.coastline.status == "available"
    ]
    lines = [*credits.values(), *dict.fromkeys(coastline_credits)]
    if _read(geo / "islands/credit.txt").splitlines() != lines:
        raise ValueError(f"{geo / 'islands/credit.txt'}: does not match {lines}")
    shapes = _coastlines(geo / "islands/coastlines.geojson", document.islands)
    membership = _membership(geo / "islands/membership.json")
    islands = {
        island.id: IslandBoundary(
            id=island.id,
            name=island.name,
            coastline=island.coastline,
            geometry=shapes.get(island.id),
        )
        for island in document.islands
    }
    districts = {
        district.fact_key: DistrictBoundary(
            id=district.fact_key,
            district=district,
            geometry=layers[chamber][district.fact_key].geometry,
            islands=tuple(islands[island] for island in membership[district.key]),
            attribution=Attribution(
                credit=credits[chamber],
                provenance=sources[chamber],
                name_authority=document.provenance.name_authority,
                membership_method=document.provenance.membership_method,
            ),
        )
        for chamber in DISTRICT_COUNTS
        for district in all_districts(chamber)
    }
    return BoundaryStore(districts=districts)
