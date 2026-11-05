"""Optional offline program metadata. Removing extensions restores legacy behavior.

Statistics are source evidence only. Runtime displays must resolve fact references
through a fact-reading tool, never render values copied from this YAML. Population
mappings and URL verification state remain separate from program records.
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, model_validator

from app.sources import Identifier, Text
from etl.programs import FORBIDDEN
from etl.programs.enrichment import Media, Statistic

_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True, str_min_length=1)
ORGANISATIONS_PATH = Path(__file__).resolve().parents[2] / "data/program_organisations.yaml"


def validate_wording(value: object) -> object:
    """Check lists, mapping keys and nested models as well as scalar prose.

    Mirrors the enrichment policy in etl/programs/enrichment.py, including whitespace
    normalization; this boundary also covers rules, referrals and legacy fields.
    """
    if isinstance(value, BaseModel):
        validate_wording(value.model_dump(mode="json"))
    elif isinstance(value, str):
        if any(ord(char) < 32 for char in value):
            raise ValueError("Catalog text contains control characters")
        if any(phrase in " ".join(value.casefold().split()) for phrase in FORBIDDEN):
            raise ValueError("Catalog text contains forbidden wording")
    elif isinstance(value, dict):
        for key, child in cast(dict[object, object], value).items():
            validate_wording(key)
            validate_wording(child)
    elif isinstance(value, (list, tuple)):
        for child in cast(list[object] | tuple[object, ...], value):
            validate_wording(child)
    return cast(object, value)


class Organisation(BaseModel):
    """Reviewed organisational endpoints only; no person or arbitrary contact fields."""

    model_config = _CONFIG
    name: Text
    source_url: HttpUrl
    public_contacts: Annotated[list[HttpUrl], Field(min_length=1)]


def load_organisations(path: Path = ORGANISATIONS_PATH) -> dict[str, Organisation]:
    """Read the maintainer-vetted registry offline; missing files fail loudly."""
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_wording(raw)
    return TypeAdapter(dict[Identifier, Organisation]).validate_python(raw)


class Contact(BaseModel):
    model_config = _CONFIG
    organisation_id: Identifier
    url: HttpUrl

    @model_validator(mode="after")
    def vetted_public_contact(self) -> Self:
        organisations = load_organisations()
        if self.organisation_id not in organisations:
            raise ValueError(f"Unknown vetted organisation: {self.organisation_id}")
        if self.url not in organisations[self.organisation_id].public_contacts:
            raise ValueError("Contact URL must be a vetted public contact endpoint")
        return self


class Rules(BaseModel):
    model_config = _CONFIG
    jurisdiction: Text
    rule_url: HttpUrl
    application_url: HttpUrl
    category: Text
    assistance_unit_definition: Text
    # These standards are not interchangeable poverty multiples.
    income_basis: Literal["census_poverty", "hawaii_hhs", "smi", "ami", "not_applicable"]
    income_period: Literal["monthly", "annual", "past_12_months", "not_applicable"]
    conditions: list[Text]
    exceptions: list[Text]
    enacted_date: date | None = None
    effective_date: date | None = None
    open_date: date | None = None
    availability: Literal["open", "closed", "waitlist", "paused", "unknown"]


class NextSteps(BaseModel):
    model_config = _CONFIG
    instructions: Annotated[list[Text], Field(min_length=1)]
    contact: Contact
    checked_at: date
    refresh_owner: Text
    refresh_after: date


class FactReference(BaseModel):
    """A fact-table join key, not an observation or proof of row availability."""

    model_config = _CONFIG
    variable: Annotated[
        Text,
        Field(
            pattern=r"^(?:[BC][0-9]{5}_[0-9]{3}E|DP[0-9]{2}_[0-9]{4}P?E|S[0-9]{4}_C[0-9]{2}_[0-9]{3}E)$"
        ),
    ]
    geography: Annotated[
        Text,
        Field(
            pattern=r"^(?:(?:house:15:0(?:0[1-9]|[1-4][0-9]|5[01])|senate:15:0(?:0[1-9]|1[0-9]|2[0-5])):2022|county:15:00[1379]|state:15)$"
        ),
    ]
    vintage: Literal["2020–2024"]


class ProgramEnrichment(BaseModel):
    """Reuse the existing provenance and reusable-media contracts unchanged."""

    model_config = _CONFIG
    stats: list[Statistic] = Field(default_factory=list[Statistic])
    media: list[Media] = Field(default_factory=list[Media])
    fact_references: list[FactReference] = Field(default_factory=list[FactReference])
