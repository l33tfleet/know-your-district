"""WO203 / WO147 step 2: the validated population registry fails loudly on bad entries."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.populations import REGISTRY_PATH, load_populations
from etl.population_variables import POPULATION_VARIABLES, POPULATIONS

FIXED_INCOME_ALTERNATIVES = {
    "older_below_poverty": ("B17001_015E", "B17001_016E", "B17001_029E", "B17001_030E"),
    "older_living_alone": ("B11007_003E",),
    "social_security": ("B19055_002E",),
}


def test_registry_carries_every_inventoried_population() -> None:
    registry = load_populations()
    entries = {p.id: p for p in registry.populations}
    assert len(entries) == len(registry.populations) == len(POPULATIONS)
    for key, planned in POPULATIONS.items():
        entry = entries[key]
        assert (entry.numerator, entry.denominator, entry.unit) == (
            planned.numerator,
            planned.denominator,
            planned.unit,
        )
        assert entry.label and entry.definition and entry.exclusions
        assert entry.comparisons == ("county", "state")
        assert entry.geography.allocation == "none"
    assert {c for p in registry.populations for c in p.numerator + p.denominator} == set(
        POPULATION_VARIABLES
    )


def test_fixed_income_is_replaced_by_three_measured_alternatives() -> None:
    entries = {p.id: p for p in load_populations().populations}
    for key, cells in FIXED_INCOME_ALTERNATIVES.items():
        assert entries[key].numerator == cells
    assert entries["retirement"].numerator == ("B19059_002E",)
    for entry in entries.values():
        assert "fixed income" not in entry.label.lower()
        tables = {c.split("_")[0] for c in entry.numerator + entry.denominator}
        assert not {"B19055", "B19059"} <= tables
    assert entries["kupuna"].label.startswith("Kūpuna")
    native = entries["native_hawaiian"]
    assert native.label == "Native Hawaiian alone or in combination"
    assert native.numerator == ("B02019_002E",)


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "populations.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _entry(data: dict[str, Any], key: str) -> dict[str, Any]:
    return next(e for e in data["populations"] if e["id"] == key)


def _shipped() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "key,field,value,error",
    [
        ("kupuna", "numerator", ["B99999_001E"], "unknown variable"),
        ("native_hawaiian", "numerator", ["B02016_002E"], "unknown variable"),
        ("kupuna", "numerator", ["B01001_020"], "string_pattern"),
        # Each compatibility case breaks exactly one of unit, universe and period.
        ("kupuna", "unit", "households", "unit persons is not households"),
        ("social_security", "denominator", ["DP04_0136E"], "universe .* is incompatible"),
        ("social_security", "universe", "Total population", "universe .* is incompatible"),
        ("social_security", "denominator", ["B11005_001E"], "period survey_time is not"),
        ("social_security", "numerator", ["B19055_002E", "B19059_002E"], "B19055 and B19059"),
        ("retirement", "denominator", ["B19055_001E"], "B19055 and B19059"),
        ("social_security", "label", "Households on a fixed income", "fixed income"),
        ("retirement", "label", "Fixed-Income households", "fixed income"),
        ("retirement", "label", "Fixed  income (retirement)", "fixed income"),
        ("social_security", "label", "Kūpuna households with Social Security", "kūpuna"),
        ("kupuna", "label", "Kupuna (65 and over)", "Hawaiian spelling"),
        ("kupuna", "definition", "Residents of Hawai'i aged 65+", "Hawaiian spelling"),
        ("kupuna", "definition", "Residents of Hawaii aged 65+", "Hawaiian spelling"),
        ("kupuna", "definition", "Residents of Lanai aged 65+", "Hawaiian spelling"),
        ("kupuna", "numerator", ["B01001_020E", "B01001_020E"], "repeats"),
        ("kupuna", "period", "past_12_months", "period"),
        ("social_security", "period", "survey_time", "period"),
        ("kupuna", "comparisons", ["state", "state"], "comparisons"),
        ("kupuna", "comparisons", ["county", "city"], "literal_error"),
        ("kupuna", "comparisons", [], "too_short"),
        ("kupuna", "numerator", [], "too_short"),
        ("kupuna", "denominator", [], "too_short"),
        ("kupuna", "exclusions", [], "too_short"),
        (
            "kupuna",
            "geography",
            {"native": "county", "plan": 2022, "allocation": "none"},
            "geography.native",
        ),
        (
            "kupuna",
            "geography",
            {"native": "state legislative district", "plan": 2012, "allocation": "none"},
            "geography.plan",
        ),
        (
            "kupuna",
            "geography",
            {
                "native": "state legislative district",
                "plan": 2022,
                "allocation": "population-weighted",
            },
            "geography.allocation",
        ),
        (
            "kupuna",
            "geography",
            {"native": "state legislative district", "plan": 2022},
            "geography.allocation",
        ),
        ("kupuna", "surprise", "x", "extra_forbidden"),
    ],
)
def test_invalid_entries_fail_loudly(
    tmp_path: Path, key: str, field: str, value: object, error: str
) -> None:
    data = _shipped()
    _entry(data, key)[field] = value
    with pytest.raises(ValidationError, match=error):
        load_populations(_write(tmp_path, data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("vintage", "2019–2023"),
        ("vintage", "2020-2024"),
        ("source", "U.S. Census Bureau ACS 1-year"),
        ("method", "modeled estimate"),
        ("populations", []),
    ],
)
def test_invalid_registry_header_fails(tmp_path: Path, field: str, value: object) -> None:
    data = _shipped()
    data[field] = value
    with pytest.raises(ValidationError, match=rf"(?m)^{field}$"):
        load_populations(_write(tmp_path, data))


def test_duplicate_ids_fail(tmp_path: Path) -> None:
    data = _shipped()
    data["populations"].append(dict(_entry(data, "kupuna")))
    with pytest.raises(ValidationError, match="duplicate population id: kupuna"):
        load_populations(_write(tmp_path, data))


def test_duplicate_yaml_keys_fail(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    path = tmp_path / "populations.yaml"
    path.write_text(text.replace("  - id: kupuna\n", "  - id: kupuna\n    id: kupuna\n"))
    with pytest.raises(ValueError, match="duplicate YAML key: id"):
        load_populations(path)


def test_correct_hawaiian_spelling_is_accepted(tmp_path: Path) -> None:
    data = _shipped()
    _entry(data, "kupuna")["definition"] = (
        "Kūpuna on Oʻahu, Kauaʻi, Lānaʻi and Molokaʻi in Hawaiʻi."
    )
    assert load_populations(_write(tmp_path, data)).populations
