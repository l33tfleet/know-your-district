"""#332: optional, safe program contracts preserve the legacy catalog."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from etl.programs import Program, load_catalog

CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


@pytest.fixture
def extended() -> dict[str, Any]:
    entry = load_catalog(CATALOG)[0].model_dump(mode="json")
    entry.update(
        rules=dict(
            jurisdiction="Hawaiʻi",
            rule_url=entry["official_url"],
            application_url=entry["official_url"],
            category="Food assistance",
            assistance_unit_definition="People purchasing and preparing meals together",
            income_basis="hawaii_hhs",
            income_period="monthly",
            conditions=["Agency household and income conditions apply"],
            exceptions=["The agency reviews exceptions"],
            enacted_date="2026-01-01",
            effective_date="2026-10-01",
            open_date="2026-10-02",
            availability="unknown",
        ),
        next_steps=dict(
            instructions=["This program may help; the agency decides eligibility"],
            contact=dict(organisation_id="auw211", url="https://www.auw211.org/"),
            checked_at="2026-10-25",
            refresh_owner="Catalog maintainers",
            refresh_after="2026-11-25",
        ),
        enrichment=dict(
            stats=[
                dict(
                    label="Households",
                    value=120,
                    unit="households",
                    geography="Hawaiʻi",
                    source="U.S. Census Bureau",
                    source_url="https://api.census.gov/data/2024/acs/acs5",
                    table_id="B22003",
                    cell="B22003_006E",
                    vintage="2020–2024",
                    method="Published estimate",
                    moe=20,
                    uncertainty=None,
                    uncertainty_reason=None,
                )
            ],
            media=[
                dict(
                    url="https://example.org/coast.jpg",
                    alt="Coast",
                    credit="Illustrative fixture",
                    origin="third-party",
                    licence="CC-BY-4.0",
                    licence_url="https://creativecommons.org/licenses/by/4.0/",
                    permission=None,
                )
            ],
            fact_references=[
                dict(
                    variable="B22003_006E",
                    geography="house:15:001:2022",
                    vintage="2020–2024",
                )
            ],
        ),
    )
    return entry


def test_original_entries_keep_legacy_serialization() -> None:
    raw = yaml.safe_load(CATALOG.read_text())
    for original, program in zip(raw, load_catalog(CATALOG), strict=True):
        assert set(program.model_dump()) == set(original) | {"retired"}
        assert set(json.loads(program.model_dump_json())) == set(original) | {"retired"}
        assert not {"rules", "next_steps", "enrichment"} & program.model_dump().keys()


def test_all_field_fixture_validates_and_round_trips(
    extended: dict[str, Any], tmp_path: Path
) -> None:
    program = Program.model_validate(extended)
    assert program.model_dump(mode="json") == extended
    assert Program.model_validate_json(program.model_dump_json()) == program
    entries = [extended, load_catalog(CATALOG)[1].model_dump(mode="json")]
    path = tmp_path / "programs.yaml"
    path.write_text(yaml.safe_dump(entries))
    assert load_catalog(path)[0] == program


@pytest.mark.parametrize("basis", ["census_poverty", "hawaii_hhs", "smi", "ami", "not_applicable"])
def test_income_standards_remain_distinct(extended: dict[str, Any], basis: str) -> None:
    extended["rules"]["income_basis"] = basis
    assert (
        Program.model_validate(extended).model_dump(mode="json")["rules"]["income_basis"] == basis
    )


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("income_basis", "poverty", "income_basis"),
        ("availability", "available sometime", "availability"),
        ("application_url", "javascript:alert(1)", "application_url"),
        ("unknown", "field", "Extra inputs"),
    ],
)
def test_rule_contract_rejects_unknown_values(
    extended: dict[str, Any],
    field: str,
    value: str,
    error: str,
) -> None:
    extended["rules"][field] = value
    with pytest.raises(ValidationError, match=error):
        Program.model_validate(extended)


@pytest.mark.parametrize(
    "contact,error",
    [
        (
            {"organisation_id": "private_person", "url": "https://www.auw211.org/"},
            "Unknown vetted organisation",
        ),
        (
            {"organisation_id": "auw211", "url": "https://www.auw211.org/staff/person"},
            "vetted public contact",
        ),
        (
            {"organisation_id": "auw211", "url": "https://private.example.org/"},
            "vetted public contact",
        ),
        (
            {
                "organisation_id": "auw211",
                "url": "https://www.auw211.org/",
                "email": "person@example.org",
            },
            "Extra inputs",
        ),
    ],
)
def test_contacts_are_only_vetted_public_endpoints(
    extended: dict[str, Any],
    contact: dict[str, str],
    error: str,
) -> None:
    extended["next_steps"]["contact"] = contact
    with pytest.raises(ValidationError, match=error):
        Program.model_validate(extended)


@pytest.mark.parametrize(
    "section,field",
    [
        ("rules", "conditions"),
        ("rules", "exceptions"),
        ("next_steps", "instructions"),
    ],
)
@pytest.mark.parametrize(
    "phrase,error",
    [
        ("You QUALIFY", "forbidden wording"),
        ("you   can get aid", "forbidden wording"),
        ("bad\x01text", "control characters"),
    ],
)
def test_recursive_safe_wording(
    extended: dict[str, Any],
    section: str,
    field: str,
    phrase: str,
    error: str,
) -> None:
    extended[section][field] = [phrase]
    with pytest.raises(ValidationError, match=error):
        Program.model_validate(extended)


@pytest.mark.parametrize("field", ["licence", "licence_url"])
def test_media_licence_omissions_fail_clearly(extended: dict[str, Any], field: str) -> None:
    del extended["enrichment"]["media"][0][field]
    with pytest.raises(ValidationError, match=field):
        Program.model_validate(extended)


@pytest.mark.parametrize(
    "field", ["source", "table_id", "cell", "vintage", "geography", "method", "moe"]
)
def test_stats_keep_provenance(extended: dict[str, Any], field: str) -> None:
    del extended["enrichment"]["stats"][0][field]
    with pytest.raises(ValidationError, match=field if field != "moe" else "uncertainty"):
        Program.model_validate(extended)


@pytest.mark.parametrize(
    "field,value",
    [
        ("variable", "invented"),
        ("geography", "house:15:999:2022"),
        ("vintage", "latest"),
        ("value", 12),
    ],
)
def test_fact_references_have_keys_and_no_observations(
    extended: dict[str, Any],
    field: str,
    value: object,
) -> None:
    extended["enrichment"]["fact_references"][0][field] = value
    with pytest.raises(ValidationError, match=field):
        Program.model_validate(extended)


def test_safe_wording_in_nested_media_permission(extended: dict[str, Any]) -> None:
    media = extended["enrichment"]["media"][0]
    media.pop("licence_url")
    media["licence"] = "permission"
    media["permission"] = dict(
        record_url="https://example.org/guaranteed",
        date="2026-10-25",
        permits_reuse=True,
    )
    with pytest.raises(ValidationError, match="forbidden wording"):
        Program.model_validate(extended)


def test_removing_extensions_restores_original(extended: dict[str, Any]) -> None:
    plain = deepcopy(extended)
    for field in ("rules", "next_steps", "enrichment"):
        del plain[field]
    assert Program.model_validate(plain) == load_catalog(CATALOG)[0]


def test_typed_extensions_cannot_bypass_wording(extended: dict[str, Any]) -> None:
    from etl.programs.contracts import Rules

    extended["rules"]["rule_url"] = "https://example.org/guaranteed"
    extended["rules"] = Rules.model_validate(extended["rules"])
    with pytest.raises(ValidationError, match="forbidden wording"):
        Program.model_validate(extended)


def test_recursive_wording_checks_mapping_keys(extended: dict[str, Any]) -> None:
    extended["rules"]["guaranteed"] = "Unsafe key"
    with pytest.raises(ValidationError, match="forbidden wording"):
        Program.model_validate(extended)


def test_recursive_wording_checks_tuples(extended: dict[str, Any]) -> None:
    extended["rules"]["conditions"] = ("Apply now",)
    with pytest.raises(ValidationError, match="forbidden wording"):
        Program.model_validate(extended)


@pytest.mark.parametrize("field", ["variable", "geography", "vintage"])
def test_fact_reference_requires_complete_key(extended: dict[str, Any], field: str) -> None:
    del extended["enrichment"]["fact_references"][0][field]
    with pytest.raises(ValidationError, match=field):
        Program.model_validate(extended)


@pytest.mark.parametrize(
    "geography",
    [
        "house:15:051:2022",
        "senate:15:025:2022",
        "county:15:001",
        "state:15",
    ],
)
def test_fact_reference_accepts_supported_geographies(
    extended: dict[str, Any],
    geography: str,
) -> None:
    extended["enrichment"]["fact_references"][0]["geography"] = geography
    assert Program.model_validate(extended).enrichment is not None


@pytest.mark.parametrize("licence", ["CC-BY-NC-4.0", "CC-BY-ND-4.0", "unknown"])
def test_program_rejects_restricted_media_licences(
    extended: dict[str, Any],
    licence: str,
) -> None:
    extended["enrichment"]["media"][0]["licence"] = licence
    with pytest.raises(ValidationError, match="licence"):
        Program.model_validate(extended)


def test_private_contact_fields_fail_even_with_vetted_url(extended: dict[str, Any]) -> None:
    extended["next_steps"]["contact"]["person"] = "Named individual"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Program.model_validate(extended)


def test_removing_validated_extensions_restores_legacy_serialization(
    extended: dict[str, Any],
) -> None:
    program = Program.model_validate(extended)
    program.rules = None
    program.next_steps = None
    program.enrichment = None
    assert program.model_dump() == load_catalog(CATALOG)[0].model_dump()
