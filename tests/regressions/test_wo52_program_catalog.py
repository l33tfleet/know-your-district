"""WO #52: offline, required catalog fields and safe population proxies."""

# Append-only rules require retaining the superseded test import.
from copy import deepcopy  # noqa: F401 # pyright: ignore[reportUnusedImport]
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from etl.programs import Program, load_catalog

CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


@pytest.fixture
def entry() -> dict[str, Any]:
    return load_catalog(CATALOG)[0].model_dump(mode="json")


@pytest.mark.parametrize(
    "phrase", ["QuAlIfY", "ELIGIBLE FOR", "You Can Get", "Guaranteed", "Apply Now"]
)
@pytest.mark.parametrize("location", ["name", "purpose", "guidance", "proxy", "guideline"])
def test_forbidden_wording_anywhere(entry: dict[str, Any], phrase: str, location: str) -> None:
    if location == "proxy":
        entry["eligibility_proxy"]["method"] = phrase
    elif location == "guideline":
        entry["agency_guideline"]["description"] = phrase
    else:
        entry[location] = phrase
    with pytest.raises(ValidationError):
        Program.model_validate(entry)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "  "),
        ("agency", None),
        ("level", "private"),
        ("official_url", "not a URL"),
        ("last_verified", "not a date"),
        ("unknown", "oops"),
    ],
)
def test_malformed_entries(entry: dict[str, Any], field: str, value: object) -> None:
    entry[field] = value
    with pytest.raises(ValidationError):
        Program.model_validate(entry)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acs_fields", []),
        ("acs_fields", ["invented"]),
        ("threshold", 1.9),
        ("poverty_line", "Hawaiʻi HHS poverty guidelines"),
        ("status", "unavailable"),
    ],
)
def test_proxy_preserves_acs_basis_and_bracket_edges(
    entry: dict[str, Any], field: str, value: object
) -> None:
    entry["eligibility_proxy"][field] = value
    with pytest.raises(ValidationError):
        Program.model_validate(entry)


def test_proxy_is_lower_bound_with_separate_guideline(entry: dict[str, Any]) -> None:
    proxy = entry["eligibility_proxy"]
    assert proxy["threshold"] == entry["agency_guideline"]["threshold"] == 2.0
    assert proxy["poverty_line"] != entry["agency_guideline"]["poverty_line"]
    assert "lower bound" in proxy["method"]
    assert "understate" in proxy["method"]
    assert proxy["vintage"] == "2020–2024"
    unavailable = load_catalog(CATALOG)[1].eligibility_proxy
    assert unavailable.acs_fields == [] and unavailable.threshold is None
    assert unavailable.method.strip()


@pytest.mark.parametrize("field", ["acs_fields", "threshold", "poverty_line", "vintage", "method"])
def test_unavailable_proxy_cannot_invent_measurements(field: str) -> None:
    programs = load_catalog(CATALOG)
    unavailable = programs[1].model_dump(mode="json")
    unavailable["eligibility_proxy"][field] = (
        " " if field == "method" else programs[0].model_dump()["eligibility_proxy"][field]
    )
    with pytest.raises(ValidationError):
        Program.model_validate(unavailable)


@pytest.mark.parametrize("content", ["", "[]", "{}", "- name: only", "!!python/object:bad {}"])
def test_loader_rejects_malformed_yaml(tmp_path: Path, content: str) -> None:
    path = tmp_path / "programs.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_catalog(path)
