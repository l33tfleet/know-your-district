"""Offline county-scoped public contacts, separate from legacy program next steps.

County identifies a service area, not a physical office or available capacity.
Organisation endpoints reuse the same reviewed allowlist as NextSteps.contact.
"""

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
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.sources import Identifier, Text
from etl.programs import load_catalog
from etl.programs.contracts import Contact, load_organisations, validate_wording

ROOT = Path(__file__).resolve().parents[1]
CONTACTS_PATH = ROOT / "data/program_contacts.yaml"
CATALOG_PATH = ROOT / "data/programs.yaml"


class ProgramContact(BaseModel):
    """A dated agency or partner endpoint serving one supported county."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: Annotated[Text, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]
    county: Literal["001", "003", "007", "009"]
    kind: Literal["agency_office", "partner"]
    organisation_id: Identifier
    url: HttpUrl
    verified_on: date

    @model_validator(mode="before")
    @classmethod
    def safe_wording(cls, value: object) -> object:
        return validate_wording(value)

    @field_validator("program_id")
    @classmethod
    def known_program(cls, value: str) -> str:
        if value not in {program.id for program in load_catalog(CATALOG_PATH)}:
            raise ValueError(f"Unknown program ID: {value}")
        return value

    @field_validator("organisation_id")
    @classmethod
    def known_organisation(cls, value: str) -> str:
        if value not in load_organisations():
            raise ValueError(f"Unknown vetted organisation: {value}")
        return value

    @field_validator("url")
    @classmethod
    def vetted_endpoint(cls, value: HttpUrl, info: ValidationInfo) -> HttpUrl:
        organisation = info.data.get("organisation_id")
        if organisation is not None:
            Contact.model_validate({"organisation_id": organisation, "url": value})
        return value

    @field_validator("verified_on")
    @classmethod
    def past_verification(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Verification date must not be in the future")
        return value


class _Contacts(BaseModel):
    """Validate cross-record identity at the file boundary."""

    contacts: list[ProgramContact]

    @model_validator(mode="after")
    def unique_contacts(self) -> Self:
        keys = [(c.program_id, c.county, c.kind, c.organisation_id, c.url) for c in self.contacts]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate program contact")
        return self


def load_contacts(path: Path = CONTACTS_PATH) -> list[ProgramContact]:
    """Read and validate the reference file without network or database access."""
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    contacts = TypeAdapter(list[ProgramContact]).validate_python(raw)
    return _Contacts(contacts=contacts).contacts
