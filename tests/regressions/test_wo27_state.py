"""WO-78: offline State service normalization and production response guards."""

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import pytest

from etl.boundaries.state import fetch_state_boundary

Chamber = Literal["house", "senate"]
FIXTURE = Path(__file__).parent / "fixtures/wo27_state.json"
CREDITS = {
    "house": "State of Hawaii Office of Elections; Hawaii Statewide GIS Program",
    "senate": "Hawaii State Office of Elections; Hawaii Statewide GIS Program",
}


def fixtures() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def response(chamber: Chamber) -> dict[str, Any]:
    data = fixtures()[chamber]
    seed = data["features"][0]
    data["features"] = [
        {**copy.deepcopy(seed), "properties": {f"{chamber}_id": f"{number:03}"}}
        for number in range(1, (51 if chamber == "house" else 25) + 1)
    ]
    return data


@pytest.mark.parametrize(("chamber", "layer", "count"), [("house", 33, 51), ("senate", 34, 25)])
def test_fetch_normalizes_and_preserves_source(chamber: Chamber, layer: int, count: int) -> None:
    urls: list[str] = []
    payload = response(chamber)
    # Keep source extras to prove only the authoritative ID is mapped.
    payload["features"][0]["properties"] = fixtures()[chamber]["features"][0]["properties"]

    def get_json(url: str) -> object:
        urls.append(url)
        return payload

    result = fetch_state_boundary(chamber, get_json=get_json, retrieved_on=date(2026, 1, 2))
    assert len(urls) == 1
    url = urlsplit(urls[0])
    assert url.scheme == "https"
    assert url.netloc == "geodata.hawaii.gov"
    assert url.path == f"/arcgis/rest/services/AdminBnd/MapServer/{layer}/query"
    assert parse_qs(url.query) == {
        "where": ["1=1"],
        "outFields": [f"{chamber}_id"],
        "f": ["geojson"],
        "outSR": ["4326"],
        "maxAllowableOffset": ["0.0005"],
        "returnGeometry": ["true"],
    }
    assert len(result.collection.features) == count
    assert [f.properties.key for f in result.collection.features] == [
        f"{chamber}-{number:02}" for number in range(1, count + 1)
    ]
    assert (
        result.collection.features[0].geometry.model_dump(mode="json")
        == payload["features"][0]["geometry"]
    )
    document = json.loads(result.geojson)
    assert len(result.geojson) < 1_000_000
    assert document["credit"] == result.credit == CREDITS[chamber]
    assert document["provenance"]["source_url"] == urls[0]
    assert document["provenance"]["retrieved_on"] == "2026-01-02"
    assert document["provenance"]["plan_year"] == 2022
    assert document["provenance"]["vintage"] == "2022 district plan"
    assert document["provenance"]["method"] == (
        "ArcGIS server generalization: maxAllowableOffset=0.0005 degrees; outSR=4326; "
        "GeoJSON; source district IDs normalized without further geometry simplification."
    )


@pytest.mark.parametrize("case", ["service_error", "truncated"])
def test_service_failures(case: str) -> None:
    message = "ArcGIS service error" if case == "service_error" else "incomplete response"
    with pytest.raises(ValueError, match=message):
        fetch_state_boundary("house", get_json=lambda _: fixtures()[case])


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_reject_partial_production_sets(chamber: Chamber) -> None:
    with pytest.raises(ValueError, match="district set mismatch"):
        fetch_state_boundary(chamber, get_json=lambda _: fixtures()[chamber])


@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("envelope", "Invalid State GeoJSON"),
        ("type", "Invalid State GeoJSON"),
        ("missing-features", "Invalid State GeoJSON"),
        ("feature", "Invalid State GeoJSON"),
        ("missing-id", "Invalid State GeoJSON"),
        ("geometry", "polygon rings must be closed"),
        ("duplicate", "duplicate district"),
        ("out-of-range", "district must be in 1..51"),
        ("nested-truncation", "incomplete response"),
    ],
)
def test_reject_malformed_responses(problem: str, message: str) -> None:
    data: Any = response("house")
    if problem == "envelope":
        data = []
    elif problem == "type":
        data["type"] = "Polygon"
    elif problem == "missing-features":
        del data["features"]
    elif problem == "feature":
        data["features"][0]["type"] = "Polygon"
    elif problem == "missing-id":
        data["features"][0]["properties"] = {"state_house": 1}
    elif problem == "geometry":
        data["features"][0]["geometry"]["coordinates"][0][-1] = [-158, 22]
    elif problem == "duplicate":
        data["features"][1]["properties"]["house_id"] = 1
    elif problem == "out-of-range":
        data["features"][0]["properties"]["house_id"] = 52
    else:
        data["properties"] = {"exceededTransferLimit": True}
    with pytest.raises(ValueError, match=message):
        fetch_state_boundary("house", get_json=lambda _: data)


def test_default_retrieval_date_is_utc_today() -> None:
    from datetime import UTC, datetime

    before = datetime.now(UTC).date()
    result = fetch_state_boundary("house", get_json=lambda _: response("house"))
    assert before <= result.collection.provenance.retrieved_on <= datetime.now(UTC).date()


@pytest.mark.parametrize("target", [999_999, 1_000_000])
def test_serialized_limit_is_strict(target: int) -> None:
    data = response("house")
    baseline = fetch_state_boundary("house", get_json=lambda _: data)
    # Redundant valid vertices pad the serialized geometry to the exact byte boundary.
    vertex_bytes = len(json.dumps([-1.0, 2.0], separators=(",", ":"))) + 1
    copies, remainder = divmod(target - len(baseline.geojson), vertex_bytes)
    padding = [[-10, 2]] * remainder + [[-1, 2]] * (copies - remainder)
    data["features"][0]["geometry"]["coordinates"][0][1:1] = padding
    if target < 1_000_000:
        assert len(fetch_state_boundary("house", get_json=lambda _: data).geojson) == target
    else:
        with pytest.raises(ValueError, match="serialized boundary must be below 1000000 bytes"):
            fetch_state_boundary("house", get_json=lambda _: data)


def test_transport_failure_propagates() -> None:
    def unavailable(_: str) -> object:
        raise OSError("synthetic network failure")

    with pytest.raises(OSError, match="synthetic network failure"):
        fetch_state_boundary("house", get_json=unavailable)
