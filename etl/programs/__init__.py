"""Offline program catalog validation; network link checks are a separate concern."""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

BRACKETS = (0.5, 1.0, 1.25, 1.5, 1.85, 2.0)
ACS_FIELDS = tuple(f"C17002_{n:03d}E" for n in range(2, 8))
FORBIDDEN = ("qualify", "eligible for", "you can get", "guaranteed", "apply now")


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, str_min_length=1)

    @field_validator("*", mode="before")
    @classmethod
    def safe_wording(cls, value: object) -> object:
        if isinstance(value, str) and any(p in value.casefold() for p in FORBIDDEN):
            raise ValueError("Catalog text contains forbidden wording")
        return value


class EligibilityProxy(CatalogModel):
    status: Literal["available", "unavailable"]
    acs_fields: list[str]
    threshold: float | None
    poverty_line: Literal["national Census poverty thresholds"] | None
    source_url: HttpUrl
    vintage: Literal["2020–2024"] | None
    geography: Literal["Hawaiʻi legislative districts, 2022 plan"]
    method: str

    @model_validator(mode="after")
    def population_proxy(self) -> Self:
        if self.status == "unavailable":
            if self.acs_fields or any(
                v is not None for v in (self.threshold, self.poverty_line, self.vintage)
            ):
                raise ValueError("Unavailable proxies must explicitly omit ACS measurements")
        else:
            if self.threshold not in BRACKETS or self.poverty_line is None or self.vintage is None:
                raise ValueError("ACS proxies require a named bracket edge and national basis")
            expected = list(ACS_FIELDS[: BRACKETS.index(self.threshold) + 1])
            if self.acs_fields != expected:
                raise ValueError(
                    "Use complete C17002 brackets below the named edge; never interpolate"
                )
            if not all(word in self.method.casefold() for word in ("lower bound", "understate")):
                raise ValueError(
                    "Explain that the national proxy is a lower bound and understates need"
                )
        return self


class AgencyGuideline(CatalogModel):
    threshold: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None
    poverty_line: Literal["Hawaiʻi HHS poverty guidelines", "not applicable"]
    effective_date: date | None
    source_url: HttpUrl
    description: str

    @model_validator(mode="after")
    def guideline_basis(self) -> Self:
        if self.poverty_line == "not applicable":
            if self.threshold is not None:
                raise ValueError("A non-poverty guideline cannot have a poverty multiple")
        elif self.threshold is None or self.effective_date is None:
            raise ValueError("Agency poverty guidelines require a threshold and effective date")
        return self


class Program(CatalogModel):
    name: str
    agency: str
    level: Literal["federal", "state", "county"]
    purpose: str
    eligibility_proxy: EligibilityProxy
    agency_guideline: AgencyGuideline
    official_url: HttpUrl
    last_verified: date
    guidance: str
    referral_url: Literal["https://www.auw211.org/"]

    @model_validator(mode="after")
    def cautious_guidance(self) -> Self:
        if "may help" not in self.purpose.casefold():
            raise ValueError("Purpose must say the program may help")
        if "agency decides eligibility" not in self.guidance.casefold():
            raise ValueError("Guidance must reserve eligibility decisions to the agency")
        return self


def load_catalog(path: Path) -> list[Program]:
    """Load only safe YAML, then validate every entry without network requests."""
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("Invalid catalog YAML") from exc
    return TypeAdapter(Annotated[list[Program], Field(min_length=1)]).validate_python(raw)
