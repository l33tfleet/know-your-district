"""#208: enrichment preserves observation evidence and media reuse rights."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from etl.programs.enrichment import Enrichment


def observation() -> dict[str, object]:
    return dict(
        label="Households",
        value=120,
        unit="households",
        geography="Hawaiʻi",
        table_id="B22003",
        cell="B22003_006E",
        vintage="2020–2024",
        method="published",
        source="U.S. Census Bureau",
        source_url="https://api.census.gov/data/2024/acs/acs5",
        moe=20,
    )


def image() -> dict[str, object]:
    return dict(
        url="https://www.nasa.gov/example.jpg",
        alt="A coastline",
        credit="Example photographer",
        origin="third-party",
        licence="CC-BY-4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
    )


@pytest.mark.parametrize(
    "field",
    [
        "label",
        "value",
        "unit",
        "geography",
        "table_id",
        "cell",
        "vintage",
        "method",
        "source",
        "source_url",
        "moe",
    ],
)
def test_observations_require_complete_evidence(field: str) -> None:
    raw = observation()
    del raw[field]
    with pytest.raises(ValidationError, match=field if field != "moe" else "uncertainty"):
        Enrichment.model_validate({"stats": [raw]})


def test_uncertainty_is_preserved_or_explicitly_unpublished() -> None:
    raw = observation()
    model = Enrichment.model_validate({"stats": [raw]})
    assert model.stats[0].model_dump()["moe"] == 20
    assert model.stats[0].geography == "Hawaiʻi"
    assert model.stats[0].cell == "B22003_006E"
    del raw["moe"]
    raw["uncertainty"] = "not-published"
    with pytest.raises(ValidationError, match="reason"):
        Enrichment.model_validate({"stats": [raw]})
    raw["uncertainty_reason"] = "Administrative count; publisher supplies no MOE"
    assert Enrichment.model_validate({"stats": [raw]}).stats[0].uncertainty == "not-published"
    raw["moe"] = 20
    with pytest.raises(ValidationError, match="uncertainty"):
        Enrichment.model_validate({"stats": [raw]})


@pytest.mark.parametrize("field", ["geography", "cell", "source", "method", "vintage"])
def test_blank_citations_are_rejected(field: str) -> None:
    raw = observation()
    raw[field] = "  "
    with pytest.raises(ValidationError, match=field):
        Enrichment.model_validate({"stats": [raw]})


@pytest.mark.parametrize("field", ["url", "alt", "credit", "origin", "licence", "licence_url"])
def test_media_requires_attribution_origin_and_rights_evidence(field: str) -> None:
    raw = image()
    del raw[field]
    with pytest.raises(ValidationError, match=field):
        Enrichment.model_validate({"media": [raw]})


@pytest.mark.parametrize(
    "licence", ["all rights reserved", "CC-BY-ND-4.0", "CC-BY-NC-4.0", "public domain", "unknown"]
)
def test_unrecognised_or_restricted_licences_fail(licence: str) -> None:
    raw = image()
    raw["licence"] = licence
    with pytest.raises(ValidationError, match="licence"):
        Enrichment.model_validate({"media": [raw]})


def test_federal_host_does_not_establish_third_party_rights() -> None:
    raw = image()
    raw["licence"] = "federal-public-domain"
    raw["licence_url"] = "https://www.nasa.gov/terms/"
    with pytest.raises(ValidationError, match="third-party"):
        Enrichment.model_validate({"media": [raw]})
    raw["origin"] = "federal-employee-work"
    assert Enrichment.model_validate({"media": [raw]}).media[0].origin == raw["origin"]


def test_reuse_licence_url_must_support_named_licence() -> None:
    raw = image()
    assert Enrichment.model_validate({"media": [raw]}).media[0].credit == raw["credit"]
    raw["licence_url"] = "https://www.nasa.gov/"
    with pytest.raises(ValidationError, match="licence_url"):
        Enrichment.model_validate({"media": [raw]})


def test_explicit_permission_requires_dated_record_and_reuse_grant() -> None:
    raw = image()
    raw.pop("licence_url")
    raw["licence"] = "permission"
    permission: dict[str, object] = dict(
        record_url="https://example.org/permission/record", date="2026-10-29", permits_reuse=True
    )
    raw["permission"] = permission
    assert Enrichment.model_validate({"media": [raw]}).media[0].permission is not None
    for field in permission:
        invalid = deepcopy(raw)
        invalid["permission"] = {k: v for k, v in permission.items() if k != field}
        with pytest.raises(ValidationError, match=field):
            Enrichment.model_validate({"media": [invalid]})


@pytest.mark.parametrize(
    "section,field",
    [("stats", "label"), ("stats", "method"), ("media", "alt"), ("media", "credit")],
)
@pytest.mark.parametrize("wording", ["You qualify", "ELIGIBLE FOR aid", "Apply now"])
def test_nested_enrichment_rejects_forbidden_wording(
    section: str, field: str, wording: str
) -> None:
    raw = observation() if section == "stats" else image()
    raw[field] = wording
    with pytest.raises(ValidationError, match="forbidden wording"):
        Enrichment.model_validate({section: [raw]})


@pytest.mark.parametrize(
    "field,value",
    [("value", float("nan")), ("value", float("inf")), ("moe", -1), ("moe", float("inf"))],
)
def test_invalid_numeric_evidence_fails(field: str, value: float) -> None:
    raw = observation()
    raw[field] = value
    with pytest.raises(ValidationError, match=field):
        Enrichment.model_validate({"stats": [raw]})


def test_enrichment_rejects_control_characters() -> None:
    raw = observation()
    raw["label"] = "a\x01b"
    with pytest.raises(ValidationError, match="control characters"):
        Enrichment.model_validate({"stats": [raw]})


def test_permission_licence_requires_permission_record() -> None:
    raw = image()
    raw.pop("licence_url")
    raw["licence"] = "permission"
    with pytest.raises(ValidationError, match="dated permission record"):
        Enrichment.model_validate({"media": [raw]})


def test_permission_record_replaces_licence_url() -> None:
    raw = image()
    raw["licence"] = "permission"
    raw["permission"] = dict(
        record_url="https://example.org/permission/record", date="2026-10-29", permits_reuse=True
    )
    with pytest.raises(ValidationError, match="instead of licence_url"):
        Enrichment.model_validate({"media": [raw]})


def test_cc_licence_cannot_use_permission_record() -> None:
    raw = image()
    raw["permission"] = dict(
        record_url="https://example.org/permission/record", date="2026-10-29", permits_reuse=True
    )
    with pytest.raises(ValidationError, match="Use licence: permission"):
        Enrichment.model_validate({"media": [raw]})


def test_permission_record_must_grant_reuse() -> None:
    raw = image()
    raw.pop("licence_url")
    raw["licence"] = "permission"
    raw["permission"] = dict(
        record_url="https://example.org/permission/record", date="2026-10-29", permits_reuse=False
    )
    with pytest.raises(ValidationError, match="permits_reuse"):
        Enrichment.model_validate({"media": [raw]})


def test_unpublished_reason_requires_explicit_uncertainty_flag() -> None:
    raw = observation()
    del raw["moe"]
    raw["uncertainty_reason"] = "Administrative count; publisher supplies no MOE"
    with pytest.raises(ValidationError) as error:
        Enrichment.model_validate({"stats": [raw]})
    assert error.value.errors()[0]["msg"] == (
        "Value error, Missing MOE requires uncertainty: not-published and a reason"
    )


def test_published_moe_rejects_uncertainty_flag_alone() -> None:
    raw = observation()
    raw["uncertainty"] = "not-published"
    with pytest.raises(ValidationError) as error:
        Enrichment.model_validate({"stats": [raw]})
    assert error.value.errors()[0]["msg"] == (
        "Value error, Published MOE cannot also have unpublished uncertainty metadata"
    )


def test_published_moe_rejects_uncertainty_reason_alone() -> None:
    raw = observation()
    raw["uncertainty_reason"] = "Administrative count; publisher supplies no MOE"
    with pytest.raises(ValidationError) as error:
        Enrichment.model_validate({"stats": [raw]})
    assert error.value.errors()[0]["msg"] == (
        "Value error, Published MOE cannot also have unpublished uncertainty metadata"
    )
