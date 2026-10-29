"""WO202 / WO147: supplemental populations preserve the baseline fact contract."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.census import CensusClient, load_config
from etl.indicators import INDICATORS, Indicator
from etl.population_variables import POPULATION_VARIABLES, POPULATIONS, load_population_config


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


@pytest.mark.skipif(not os.environ.get("WO202_VERIFY_CENSUS"), reason="opt-in Census verification")
def test_published_metadata_and_both_chambers() -> None:
    """Replay: WO202_VERIFY_CENSUS=1 CENSUS_API_KEY=… uv run pytest <this-id>."""
    client = CensusClient(load_population_config(), api_key=os.environ.get("CENSUS_API_KEY"))
    # Also verify the unselected alone definition; never combine it with B02019.
    variables = sorted(set(POPULATION_VARIABLES) | {"B02016_002E"})
    jobs: list[tuple[Indicator, str, int]] = []
    for endpoint in ("detailed", "profile", "subject"):
        selected = [
            v
            for v in variables
            if ("profile" if v.startswith("DP") else "subject" if v.startswith("S") else "detailed")
            == endpoint
        ]
        for start in range(0, len(selected), 12):
            group = Indicator(tuple(selected[start : start + 12]), endpoint)
            for chamber, count in (("lower", 51), ("upper", 25)):
                jobs.append((group, chamber, count))

    def verify(job: tuple[Indicator, str, int]) -> None:
        group, chamber, count = job
        geography = f"state legislative district ({chamber} chamber)"
        batch = client.fetch(group, geography + ":*")
        assert {r[geography] for r in batch.rows} == {f"{n:03}" for n in range(1, count + 1)}
        for row in batch.rows:
            assert row["state"] == "15"
            for variable in group.variables:
                for column in (variable, group.moe_variable(variable)):
                    value = row[column]
                    assert value is not None, (column, row[geography])
                    if column.endswith("M") and value == "-555555555":
                        assert row[column + "A"] == "*****"  # Published controlled MOE.
                    else:
                        assert float(value) >= 0, (column, row[geography])
                        assert row[column + "A"] in (None, ""), (column, row[geography])

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(verify, jobs))


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
