"""WO202 / WO147: supplemental populations preserve the baseline fact contract."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.census import CensusBatch, CensusClient, CensusError, load_config
from etl.indicators import INDICATORS, Indicator
from etl.population_variables import (
    POPULATION_VARIABLES,
    POPULATIONS,
    load_population_config,
    verify_district_availability,
)


def cells(table: str, *numbers: int) -> tuple[str, ...]:
    return tuple(f"{table}_{number:03}E" for number in numbers)


CHILDREN = (*range(4, 10), *range(18, 24))
OLDER = (15, 16, 29, 30)
EXPECTED = {
    "children_under_5": (cells("B01001", 3, 27), cells("B01001", 1)),
    "children_below_poverty": (
        cells("B17001", *CHILDREN),
        cells("B17001", *CHILDREN, *(n + 29 for n in CHILDREN)),
    ),
    "households_with_children": (cells("B11005", 2), cells("B11005", 1)),
    "native_hawaiian": (cells("B02019", 2), cells("B01001", 1)),
    "kupuna": (cells("B01001", *range(20, 26), *range(44, 50)), cells("B01001", 1)),
    "older_below_poverty": (
        cells("B17001", *OLDER),
        cells("B17001", *OLDER, *(n + 29 for n in OLDER)),
    ),
    "older_living_alone": (cells("B11007", 3), cells("B11007", 1)),
    "social_security": (cells("B19055", 2), cells("B19055", 1)),
    "retirement": (cells("B19059", 2), cells("B19059", 1)),
    "disability": (("S1810_C02_001E",), ("S1810_C01_001E",)),
    "rent_burden": (("DP04_0141E", "DP04_0142E"), ("DP04_0136E",)),
    "below_200_percent_poverty": (cells("C17002", *range(2, 8)), cells("C17002", 1)),
    "below_poverty_no_snap": (cells("B22003", 6), cells("B22003", 3, 6)),
}


def test_complete_population_and_denominator_mapping() -> None:
    assert {key: (p.numerator, p.denominator) for key, p in POPULATIONS.items()} == EXPECTED
    expected = {v for pair in EXPECTED.values() for side in pair for v in side}
    assert set(POPULATION_VARIABLES) == expected
    assert len(POPULATION_VARIABLES) == len(expected)
    for key, population in POPULATIONS.items():
        assert population.label and population.universe
        household = key in {
            "households_with_children",
            "older_living_alone",
            "social_security",
            "retirement",
            "rent_burden",
            "below_poverty_no_snap",
        }
        assert population.unit == ("households" if household else "persons")
    assert POPULATIONS["native_hawaiian"].label == "Native Hawaiian alone or in combination"
    assert "fixed income" not in " ".join(p.label.lower() for p in POPULATIONS.values())


def test_exact_published_population_labels() -> None:
    labels = load_population_config().labels
    # SHA-256 of sorted `variable=label\n`, independently fetched from 2024 metadata.
    actual = "".join(f"{v}={labels[v]}\n" for v in sorted(POPULATION_VARIABLES))
    assert (
        hashlib.sha256(actual.encode()).hexdigest()
        == "945c2ed6552a61823ea087a5b730f96b9c4c323cafa40b1684cbe7ee539203a0"
    )


class FakeCensus(CensusClient):
    """Offline stand-in for label-checked data; `broken` sets one district cell to `value`."""

    def __init__(self, broken: tuple[str, str, str] = ("", "", ""), value: str | None = None):
        super().__init__(load_population_config())
        self.broken, self.value, self.upper = broken, value, 25
        self.requested: set[str] = set()
        self.calls = {"lower": 0, "upper": 0}

    def fetch(self, indicator: Indicator, geography: str) -> CensusBatch:
        chamber = "lower" if "(lower chamber)" in geography else "upper"
        key = geography.removesuffix(":*")
        self.requested.update(indicator.variables)
        self.calls[chamber] += 1
        rows: list[dict[str, str | None]] = []
        for n in range(1, (51 if chamber == "lower" else self.upper) + 1):
            row: dict[str, str | None] = {"state": "15", key: f"{n:03}"}
            for v in indicator.variables:
                m = indicator.moe_variable(v)
                row |= {v: "120", m: "-555555555", v + "A": None, m + "A": "*****"}
            if self.broken[:2] == (chamber, f"{n:03}") and self.broken[2] in row:
                row[self.broken[2]] = self.value
            rows.append(row)
        labels = {v: self.config.labels[v] for v in indicator.variables}
        return CensusBatch("fake", self.config.vintage, labels, rows)


def test_published_metadata_and_both_chambers() -> None:
    client = FakeCensus()
    checked = verify_district_availability(client)
    assert client.calls["lower"] == client.calls["upper"] > 0
    assert checked == 76 * client.calls["lower"]
    # Both Native Hawaiian definitions are checked; only B02019 (in combination) is used.
    assert client.requested == {*POPULATION_VARIABLES, "B02016_002E", "B02019_002E"}
    assert "B02016_002E" not in POPULATION_VARIABLES


@pytest.mark.parametrize(
    "broken,value",
    [
        (("upper", "025", "B02016_002E"), None),
        (("upper", "001", "B02019_002E"), None),
        (("lower", "051", "B02019_002M"), None),
        (("lower", "014", "S1810_C02_001E"), None),
        (("upper", "007", "DP04_0142E"), None),
        (("lower", "001", "state"), None),
        (("lower", "010", "B19055_002E"), "-666666666"),
        (("lower", "010", "B19059_002E"), "n/a"),
        (("upper", "010", "B11007_003EA"), "-"),
        (("upper", "010", "B01001_001MA"), "***"),
    ],
)
def test_availability_rejects_a_missing_district_cell(
    broken: tuple[str, str, str], value: str | None
) -> None:
    with pytest.raises(CensusError, match=f"district {broken[1]} \\({broken[0]} chamber"):
        verify_district_availability(FakeCensus(broken, value))


def test_availability_rejects_a_missing_district() -> None:
    client = FakeCensus()
    client.upper = 24
    with pytest.raises(CensusError, match="upper chamber"):
        verify_district_availability(client)


def test_population_configuration_is_isolated() -> None:
    baseline = load_config()
    population = load_population_config()
    assert set(baseline.labels) == {v for g in INDICATORS.values() for v in g.variables}
    assert "B22003_006E" in population.labels
    assert population.labels.items() >= baseline.labels.items()


@pytest.mark.parametrize(
    "invalid,error", [('"invalid"', "dict_type"), ("{bad = 123}", "string_type")]
)
def test_population_labels_reject_invalid_types(tmp_path: Path, invalid: str, error: str) -> None:
    baseline = Path("config.toml").read_text().split("[population_labels]")[0]
    path = tmp_path / "config.toml"
    path.write_text(f"population_labels = {invalid}\n" + baseline)
    with pytest.raises(ValidationError, match=error):
        load_population_config(path)
