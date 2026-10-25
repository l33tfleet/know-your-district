"""Offline contract checks for chamber-aware boundary normalization (WO-47)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from etl.boundaries import BoundaryCollection, DistrictId

FIXTURE = Path(__file__).parent / "fixtures" / "wo47_boundaries.geojson"


def fixture_data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("number", [1, "1", "01", "001"])
def test_padding_and_chamber_collision(number: str | int) -> None:
    house = DistrictId(chamber="house", district=number)
    senate = DistrictId(chamber="senate", district=number)
    assert house.key == "house-01"
    assert senate.key == "senate-01"
    assert house.key != senate.key
    assert house.census_code == senate.census_code == "001"


@pytest.mark.parametrize(
    ("chamber", "number"),
    [
        ("house", 0),
        ("house", 52),
        ("senate", 26),
        ("upper", 1),
        ("house", True),
        ("house", 1.0),
        ("house", "1.0"),
        ("house", "-1"),
        ("house", " 1"),
        ("house", "0001"),
        ("house", "\uff11"),
        ("house", "house-01"),
    ],
)
def test_invalid_ids(chamber: str, number: object) -> None:
    with pytest.raises(ValidationError):
        DistrictId.model_validate({"chamber": chamber, "district": number})


def test_district_endpoints() -> None:
    assert DistrictId(chamber="house", district=51).key == "house-51"
    assert DistrictId(chamber="senate", district="025").key == "senate-25"


def test_fixture_preserves_provenance_and_separates_chambers() -> None:
    collection = BoundaryCollection.model_validate(fixture_data())
    assert [feature.properties.key for feature in collection.features] == ["house-01", "senate-01"]
    assert collection.provenance.plan_year == 2022
    assert collection.provenance.method == "synthetic test geometry; not official boundaries"
    assert "example.org" in str(collection.provenance.source_url)


def test_duplicates_rejected_after_padding_normalization() -> None:
    data = fixture_data()
    duplicate = json.loads(json.dumps(data["features"][0]))
    duplicate["properties"]["district"] = "01"
    data["features"].append(duplicate)
    with pytest.raises(ValidationError, match="duplicate district: house-01"):
        BoundaryCollection.model_validate(data)


@pytest.mark.parametrize("field", ["source_url", "retrieved_on", "vintage", "method"])
def test_missing_provenance_rejected(field: str) -> None:
    data = fixture_data()
    del data["provenance"][field]
    with pytest.raises(ValidationError):
        BoundaryCollection.model_validate(data)


@pytest.mark.parametrize("problem", ["open_ring", "null_geometry", "point", "bad_id", "empty"])
def test_invalid_features_rejected(problem: str) -> None:
    data = fixture_data()
    feature = data["features"][0]
    if problem == "open_ring":
        feature["geometry"]["coordinates"][0][-1] = [-157.0, 21.0]
    elif problem == "null_geometry":
        feature["geometry"] = None
    elif problem == "point":
        feature["geometry"] = {"type": "Point", "coordinates": [-155.0, 20.0]}
    elif problem == "bad_id":
        feature["properties"]["district"] = "999"
    else:
        data["features"] = []
    with pytest.raises(ValidationError):
        BoundaryCollection.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", "file:///tmp/source"),
        ("retrieved_on", "yesterday"),
        ("plan_year", 2012),
        ("vintage", " "),
        ("method", ""),
    ],
)
def test_invalid_provenance_rejected(field: str, value: object) -> None:
    data = fixture_data()
    data["provenance"][field] = value
    with pytest.raises(ValidationError):
        BoundaryCollection.model_validate(data)


@pytest.mark.parametrize("position", [[181, 20], [-155, 91], [float("inf"), 20]])
def test_out_of_range_coordinates_rejected(position: list[float]) -> None:
    data = fixture_data()
    data["features"][0]["geometry"]["coordinates"][0][1] = position
    with pytest.raises(ValidationError):
        BoundaryCollection.model_validate(data)


def test_degenerate_multipolygon_rejected() -> None:
    data = fixture_data()
    data["features"][1]["geometry"]["coordinates"] = [
        [[[-155, 20], [-155, 20], [-155, 20], [-155, 20]]]
    ]
    with pytest.raises(ValidationError):
        BoundaryCollection.model_validate(data)
