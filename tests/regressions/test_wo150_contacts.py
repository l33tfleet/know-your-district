"""#371: county-scoped program contacts reuse vetted public organisations."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.program_contacts import ProgramContact, load_contacts
from etl.programs import load_catalog
from etl.programs.contracts import Contact, load_organisations


@pytest.fixture
def record() -> dict[str, object]:
    return {
        "program_id": "snap",
        "county": "003",
        "kind": "partner",
        "organisation_id": "auw211",
        "url": "https://www.auw211.org/",
        "verified_on": "2026-10-28",
    }


def test_county_scoped_contacts_validate() -> None:
    contacts = load_contacts()
    assert contacts
    assert {c.kind for c in contacts} == {"agency_office", "partner"}
    assert {c.county for c in contacts} == {"001", "003", "007", "009"}
    organisations = load_organisations()
    programs = load_catalog(Path("data/programs.yaml"))
    assert all(c.program_id in {p.id for p in programs} for c in contacts)
    assert all(c.url in organisations[c.organisation_id].public_contacts for c in contacts)
    assert all(c.verified_on <= date.today() for c in contacts)
    # The legacy next-step contract and all existing catalog records still load.
    for program in programs:
        if program.next_steps:
            assert Contact.model_validate(program.next_steps.contact.model_dump())


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("program_id", "unknown-program", "value_error"),
        ("program_id", "snap?fields=all", "string_pattern_mismatch"),
        ("county", "005", "literal_error"),
        ("county", "999", "literal_error"),
        ("county", "Honolulu", "literal_error"),
        ("county", 3, "literal_error"),
        ("kind", "person", "literal_error"),
        ("organisation_id", "unknown", "value_error"),
        ("verified_on", "yesterday", "date_from_datetime_parsing"),
        ("verified_on", "2999-01-01", "value_error"),
        ("email", "person@example.org", "extra_forbidden"),
    ],
)
def test_invalid_contact_fields_fail_specifically(
    record: dict[str, object], field: str, value: object, error_type: str
) -> None:
    record[field] = value
    with pytest.raises(ValidationError) as caught:
        ProgramContact.model_validate(record)
    assert [(e["loc"], e["type"]) for e in caught.value.errors()] == [((field,), error_type)]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.auw211.org/staff/person",
        "https://www.auw211.org/?person=someone",
        "https://www.auw211.org/#person",
        "https://www.auw211.org.evil.example/",
        "https://humanservices.hawaii.gov/bessd/snap/",
        "https://person:secret@www.auw211.org/",
        "http://www.auw211.org/",
    ],
)
def test_unvetted_endpoints_fail(record: dict[str, object], url: str) -> None:
    record["url"] = url
    with pytest.raises(ValidationError, match="vetted public contact endpoint") as caught:
        ProgramContact.model_validate(record)
    assert caught.value.errors()[0]["loc"] == ("url",)


@pytest.mark.parametrize(
    "field", ["program_id", "county", "kind", "organisation_id", "url", "verified_on"]
)
def test_contact_fields_are_required(record: dict[str, object], field: str) -> None:
    del record[field]
    with pytest.raises(ValidationError) as caught:
        ProgramContact.model_validate(record)
    assert [(e["loc"], e["type"]) for e in caught.value.errors()] == [((field,), "missing")]


def test_loader_validates_files_and_rejects_duplicates(
    record: dict[str, object], tmp_path: Path
) -> None:
    path = tmp_path / "contacts.yaml"
    path.write_text(yaml.safe_dump([record]))
    contact = load_contacts(path)[0]
    assert contact.county == "003"
    assert contact.verified_on == date(2026, 10, 28)
    path.write_text(yaml.safe_dump([record, record]))
    with pytest.raises(ValueError, match="Duplicate program contact"):
        load_contacts(path)
    record["program_id"] = "unknown-program"
    path.write_text(yaml.safe_dump([record]))
    with pytest.raises(ValidationError, match="Unknown program ID: unknown-program"):
        load_contacts(path)
