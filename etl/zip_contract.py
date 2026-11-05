"""Offline ZIP contracts for #134. No ACS facts, network access or output writes."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, model_validator

from etl.boundaries import DistrictId, MultiPolygon, Polygon

Code = Annotated[str, Field(pattern=r"^[0-9]{5}$", strict=True)]
# Identifiers and citation text cannot carry control characters or query syntax.
Text = Annotated[str, Field(min_length=1, pattern=re.compile(r"^(?!.*\.\.)[^\x00-\x1f\x7f?%#]+\Z"))]
Population = Annotated[int, Field(ge=0, strict=True)]
Denominator = Annotated[int, Field(gt=0, strict=True)]


class TaxObservation(BaseModel):
    """Published administrative cell; status never becomes a fabricated zero or MOE."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    zip: Code
    measure: Text
    filing_status: Text
    year: int = Field(ge=1900, le=9999, strict=True)
    units: Text
    value: Annotated[Decimal, Field(allow_inf_nan=False)] | None
    status: Literal["published", "suppressed", "unavailable"]
    table: Text
    source_url: HttpUrl
    retrieved_on: date

    @model_validator(mode="after")
    def value_matches_status(self) -> Self:
        if self.status == "published" and self.value is None:
            raise ValueError("published requires a value")
        if self.status != "published" and self.value is not None:
            raise ValueError("suppressed/unavailable requires null")
        return self

    @property
    def key(self) -> tuple[str, str, str, int]:
        return self.zip, self.measure, self.filing_status, self.year


class CrosswalkRow(BaseModel):
    """Population intersection and denominators, never normalized polygon areas."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    zcta: Code
    district: DistrictId
    intersection_population: Population
    zcta_population: Denominator
    district_population: Denominator
    population_year: Literal[2020]
    method: Literal["population-weighted (2020 blocks)"]
    source_url: HttpUrl
    retrieved_on: date

    @model_validator(mode="after")
    def bounded_intersection(self) -> Self:
        if self.intersection_population > min(self.zcta_population, self.district_population):
            raise ValueError("intersection exceeds denominator")
        return self

    @property
    def zcta_share(self) -> float:
        return self.intersection_population / self.zcta_population

    @property
    def district_share(self) -> float:
        return self.intersection_population / self.district_population

    @property
    def key(self) -> tuple[str, str]:
        return self.zcta, self.district.fact_key


class ZctaGeometry(BaseModel):
    """Normalized Census geometry; its code is not proof of a postal ZIP match."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    zcta: Code
    vintage: Literal[2020]
    geometry: Annotated[Polygon | MultiPolygon, Field(discriminator="type")]
    source_url: HttpUrl
    retrieved_on: date

    @property
    def key(self) -> str:
        return self.zcta


class UnmappableZIP(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    zip: Code
    reason: Text

    @property
    def key(self) -> str:
        return self.zip


def read_records[T: (TaxObservation, CrosswalkRow, ZctaGeometry, UnmappableZIP)](
    path: Path, record_type: type[T]
) -> list[T]:
    """Read a normalized JSON array; fail rather than overwrite duplicate identities."""
    raw = TypeAdapter(list[object]).validate_json(path.read_bytes())
    records = [record_type.model_validate(row) for row in raw]
    if len({row.key for row in records}) != len(records):
        raise ValueError("duplicate record key")
    return records


def read_tax(path: Path) -> list[TaxObservation]:
    return read_records(path, TaxObservation)


def read_crosswalk(path: Path) -> list[CrosswalkRow]:
    return read_records(path, CrosswalkRow)
