"""WO176 / WO139 step 1: validated manifests preserve the published ACS registry."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.copy import section_copy
from app.sources import SourceManifest, load_source
from etl.build import BUILD_INDICATORS
from etl.census import load_config
from etl.indicators import INDICATORS


def test_manifest_matches_existing_registry() -> None:
    source = load_source()
    config = load_config()
    assert source.name == "U.S. Census Bureau ACS 5-year"
    assert str(source.url) == config.base_url.format(year=config.year)
    assert source.vintage == config.vintage
    assert "public domain" in source.licence
    assert source.geography.state == "15"
    assert source.geography.district_plan == 2022
    assert source.geography.county_codes == ("001", "003", "007", "009")
    assert tuple(i.id for i in source.indicators if i.build) == BUILD_INDICATORS
    assert {i.id for i in source.indicators} == INDICATORS.keys()
    names = section_copy("figures")["names"]
    for group in source.indicators:
        old = INDICATORS[group.id]
        assert group.endpoint == old.endpoint
        assert tuple(v.id for v in group.variables) == old.variables
        for variable in group.variables:
            assert variable.expected_label == config.labels[variable.id].format(year=config.year)
            assert variable.display_name
            if group.id in names:
                assert variable.display_name == names[group.id]
    assert sum(len(i.variables) for i in source.indicators) == 25


@pytest.mark.parametrize(
    "field", ["name", "url", "licence", "geography", "vintage", "method", "indicators"]
)
def test_source_metadata_required(field: str) -> None:
    data = load_source().model_dump()
    del data[field]
    with pytest.raises(ValidationError, match=field):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize("field", ["id", "endpoint", "build", "variables"])
def test_group_contract_required(field: str) -> None:
    data = load_source().model_dump()
    del data["indicators"][0][field]
    with pytest.raises(ValidationError, match=field):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize("field", ["id", "expected_label", "display_name", "unit"])
def test_display_contract_required(field: str) -> None:
    data = load_source().model_dump()
    del data["indicators"][0]["variables"][0][field]
    with pytest.raises(ValidationError, match=field):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize(
    "path,value,error",
    [
        (("vintage",), "latest", "vintage"),
        (("url",), "https://api.census.gov/data/2023/acs/acs5", "url"),
        (("method",), "derived sum", "method"),
        (("geography", "state"), "06", "state"),
        (("geography", "district_plan"), 2012, "district_plan"),
        (("geography", "county_codes"), ["005"], "county_codes"),
        (("indicators", 0, "endpoint"), "other", "endpoint"),
        (("indicators", 0, "endpoint"), "profile", "endpoint disagrees"),
        (("indicators", 0, "build"), "yes", "build"),
        (("indicators", 10, "variables", 0, "id"), "DP05_0030PE", "one table"),
        (("indicators", 0, "id"), "../population", "id"),
        (("indicators", 0, "variables"), [], "variables"),
        (("indicators",), [], "indicators"),
        (("indicators", 0, "variables", 0, "id"), "B01003_001M", "id"),
        (("indicators", 0, "variables", 0, "unit"), "widgets", "unit"),
        (("indicators", 1, "variables", 0, "unit"), "people", "percent unit"),
        (("indicators", 0, "variables", 0, "display_name"), "  ", "display_name"),
        (("name",), "Census\nBureau", "control characters"),
        (("unexpected",), True, "extra_forbidden"),
        (("indicators", 0, "unexpected"), True, "extra_forbidden"),
        (("indicators", 0, "variables", 0, "unexpected"), True, "extra_forbidden"),
        (("geography", "unexpected"), True, "extra_forbidden"),
    ],
)
def test_unsupported_contracts(path: tuple[str | int, ...], value: object, error: str) -> None:
    data = load_source().model_dump(mode="json")
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError, match=error):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize("kind", ["group", "variable"])
def test_duplicate_definitions_rejected(kind: str) -> None:
    data = load_source().model_dump(mode="json")
    duplicate = data["indicators"][0].copy()
    if kind == "variable":
        duplicate["id"] = "another_population"
    data["indicators"].append(duplicate)
    with pytest.raises(ValidationError, match=f"duplicate {kind}"):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize(
    "content", ["name: Census\nname: Other\n", "geography: {state: 15, state: 06}"]
)
def test_duplicate_yaml_keys_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        load_source(path)


@pytest.mark.parametrize("content", ["", "null", "[]"])
def test_empty_manifest_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_source(path)
