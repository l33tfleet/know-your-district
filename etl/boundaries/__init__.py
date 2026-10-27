"""Offline boundary input contract; shared district keys for the WO-3 ETL."""

import re
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, ValidationInfo
from pydantic.functional_validators import field_validator, model_validator

Chamber = Literal["house", "senate"]
DISTRICT_COUNTS: dict[Chamber, int] = {"house": 51, "senate": 25}


class DistrictId(BaseModel):
    """Normalize a chamber and an ASCII district code without losing chamber identity."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    chamber: Chamber
    district: int | str

    @field_validator("district")
    @classmethod
    def normalize_number(cls, value: int | str, info: ValidationInfo) -> int:
        if isinstance(value, str) and not re.fullmatch(r"[0-9]{1,3}", value):
            raise ValueError("district must be one to three ASCII digits")
        number = int(value)
        # An invalid chamber is reported by its own field validator.
        chamber: Chamber = info.data.get("chamber", "senate")
        limit = DISTRICT_COUNTS[chamber]
        if not 1 <= number <= limit:
            raise ValueError(f"district must be in 1..{limit} for its chamber")
        return number

    @property
    def key(self) -> str:
        return f"{self.chamber}-{int(self.district):02d}"

    @property
    def census_code(self) -> str:
        return f"{int(self.district):03d}"

    @property
    def fact_key(self) -> str:
        return f"{self.chamber}:15:{self.census_code}:2022"


def all_districts(chamber: Chamber) -> list[DistrictId]:
    """Return every district in the chamber in numeric order."""
    return [
        DistrictId(chamber=chamber, district=number)
        for number in range(1, DISTRICT_COUNTS[chamber] + 1)
    ]


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_url: HttpUrl
    retrieved_on: date
    vintage: str = Field(min_length=1)
    plan_year: Literal[2022]
    method: str = Field(min_length=1)

    @field_validator("retrieved_on", mode="before")
    @classmethod
    def validate_retrieval_date(cls, value: object) -> date:
        if type(value) is date:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return date.fromisoformat(value)
        raise ValueError("retrieved_on must be an ISO calendar date (YYYY-MM-DD)")


Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)]
Position = tuple[Longitude, Latitude]
Ring = Annotated[list[Position], Field(min_length=4)]
Rings = Annotated[list[Ring], Field(min_length=1)]


def check_rings(rings: Rings) -> Rings:
    for ring in rings:
        if ring[0] != ring[-1]:
            raise ValueError("polygon rings must be closed")
        if len(set(ring[:-1])) < 3:
            raise ValueError("polygon rings need three distinct vertices")
    return rings


ValidatedRings = Annotated[Rings, AfterValidator(check_rings)]


class Polygon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Polygon"]
    coordinates: ValidatedRings


class MultiPolygon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["MultiPolygon"]
    coordinates: list[ValidatedRings] = Field(min_length=1)


class BoundaryFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    properties: DistrictId
    geometry: Annotated[Polygon | MultiPolygon, Field(discriminator="type")]


class BoundaryCollection(BaseModel):
    """Validate a normalized input profile, including collisions after padding."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"]
    provenance: Provenance
    features: list[BoundaryFeature] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_districts(self) -> Self:
        seen: set[str] = set()
        for feature in self.features:
            key = feature.properties.key
            if key in seen:
                raise ValueError(f"duplicate district: {key}")
            seen.add(key)
        return self
