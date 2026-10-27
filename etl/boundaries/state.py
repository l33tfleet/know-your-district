"""Fetch the State's 2022 district layers with an injectable JSON transport.

The returned UTF-8 GeoJSON bytes are the production file contents: validated
complete chamber coverage, provenance and the layer's verbatim required credit.
No local topology or simplification claims are made beyond the server request.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from etl.boundaries import BoundaryCollection, Chamber, all_districts

BASE_URL = "https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer"
# Verbatim copyrightText from each layer's ?f=pjson metadata; the wording differs.
LAYERS: dict[Chamber, tuple[int, str]] = {
    "house": (33, "State of Hawaii Office of Elections; Hawaii Statewide GIS Program"),
    "senate": (34, "Hawaii State Office of Elections; Hawaii Statewide GIS Program"),
}
METHOD = (
    "ArcGIS server generalization: maxAllowableOffset=0.0005 degrees; outSR=4326; "
    "GeoJSON; source district IDs normalized without further geometry simplification."
)


class _SourceFeature(BaseModel):
    type: Literal["Feature"]
    properties: dict[str, object]
    geometry: dict[str, object]


class _SourceCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[_SourceFeature]
    properties: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class StateBoundary:
    collection: BoundaryCollection
    credit: str
    geojson: bytes


def _get_json(url: str) -> object:
    with urlopen(url, timeout=30) as response:
        payload: object = json.loads(response.read())
    return payload


def fetch_state_boundary(
    chamber: Chamber,
    *,
    get_json: Callable[[str], object] = _get_json,
    retrieved_on: date | None = None,
) -> StateBoundary:
    """Fetch one complete chamber, failing before returning any production bytes.

    Injection replaces only HTTP/JSON decoding, so offline callers exercise the
    same normalization, coverage and serialized-size validation as production.
    HTTP/JSON decoding failures propagate from the transport to the operator.
    """
    layer, credit = LAYERS[chamber]
    field = f"{chamber}_id"
    url = f"{BASE_URL}/{layer}/query?" + urlencode(
        {
            "where": "1=1",
            "outFields": field,
            "f": "geojson",
            "outSR": "4326",
            "maxAllowableOffset": "0.0005",
            "returnGeometry": "true",
        }
    )
    payload = get_json(url)
    try:
        envelope = TypeAdapter(dict[str, object]).validate_python(payload, strict=True)
    except ValidationError:
        raise ValueError("Invalid State GeoJSON") from None
    if "error" in envelope:
        raise ValueError("ArcGIS service error")
    if envelope.get("exceededTransferLimit"):
        raise ValueError("incomplete response: exceededTransferLimit")
    try:
        source = _SourceCollection.model_validate(envelope)
        # ArcGIS GeoJSON may put transfer-limit information in foreign properties.
        if source.properties.get("exceededTransferLimit"):
            raise ValueError("incomplete response: exceededTransferLimit")
        features = [
            {
                "type": feature.type,
                "properties": {"chamber": chamber, "district": feature.properties[field]},
                "geometry": feature.geometry,
            }
            for feature in source.features
        ]
    except (ValidationError, KeyError):
        raise ValueError("Invalid State GeoJSON") from None
    collection = BoundaryCollection.model_validate(
        {
            "type": "FeatureCollection",
            "provenance": {
                "source_url": url,
                "retrieved_on": retrieved_on
                if retrieved_on is not None
                else datetime.now(UTC).date(),
                "vintage": "2022 district plan",
                "plan_year": 2022,
                "method": METHOD,
            },
            "features": features,
        }
    )
    expected = {district.key for district in all_districts(chamber)}
    actual = {feature.properties.key for feature in collection.features}
    if actual != expected:
        raise ValueError(
            f"district set mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    collection.features.sort(key=lambda feature: feature.properties.key)
    document = collection.model_dump(mode="json") | {"credit": credit}
    serialized = (
        json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(serialized) >= 1_000_000:
        raise ValueError("serialized boundary must be below 1000000 bytes")
    return StateBoundary(collection, credit, serialized)
