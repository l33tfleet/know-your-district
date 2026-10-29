"""Supplemental published-cell acquisition plan for WO147; no observations or sums.

Independent of etl.indicators and data/sources/acs.yaml. Numerator/denominator
cell sums belong in later pure analysis; definitions and exclusions: docs/data.md.
"""

import os
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from etl.census import ACSConfig, CensusClient, CensusError, load_config
from etl.indicators import Indicator


@dataclass(frozen=True)
class PopulationVariables:
    label: str
    unit: Literal["persons", "households"]
    universe: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]


def _cells(table: str, *numbers: int) -> tuple[str, ...]:
    return tuple(f"{table}_{number:03}E" for number in numbers)


_CHILDREN = (*range(4, 10), *range(18, 24))
_OLDER = (15, 16, 29, 30)
_POVERTY_UNIVERSE = "Population for whom poverty status is determined"

POPULATIONS = {
    "children_under_5": PopulationVariables(
        "Children under 5",
        "persons",
        "Total population",
        _cells("B01001", 3, 27),
        _cells("B01001", 1),
    ),
    "children_below_poverty": PopulationVariables(
        "Children under 18 below poverty",
        "persons",
        _POVERTY_UNIVERSE,
        _cells("B17001", *_CHILDREN),
        _cells("B17001", *_CHILDREN, *(n + 29 for n in _CHILDREN)),
    ),
    "households_with_children": PopulationVariables(
        "Households with children under 18",
        "households",
        "Households",
        _cells("B11005", 2),
        _cells("B11005", 1),
    ),
    "native_hawaiian": PopulationVariables(
        "Native Hawaiian alone or in combination",
        "persons",
        "Total Native Hawaiian and Other Pacific Islander alone or in any combination "
        "who reported one or more responses",
        _cells("B02019", 2),
        _cells("B01001", 1),
    ),
    "kupuna": PopulationVariables(
        "Kūpuna (65 years and over)",
        "persons",
        "Total population",
        _cells("B01001", *range(20, 26), *range(44, 50)),
        _cells("B01001", 1),
    ),
    "older_below_poverty": PopulationVariables(
        "Residents 65 years and over below poverty",
        "persons",
        _POVERTY_UNIVERSE,
        _cells("B17001", *_OLDER),
        _cells("B17001", *_OLDER, *(n + 29 for n in _OLDER)),
    ),
    "older_living_alone": PopulationVariables(
        "Households with a person 65 years and over living alone",
        "households",
        "Households",
        _cells("B11007", 3),
        _cells("B11007", 1),
    ),
    "social_security": PopulationVariables(
        "Households with Social Security income",
        "households",
        "Households",
        _cells("B19055", 2),
        _cells("B19055", 1),
    ),
    "retirement": PopulationVariables(
        "Households with retirement income",
        "households",
        "Households",
        _cells("B19059", 2),
        _cells("B19059", 1),
    ),
    "disability": PopulationVariables(
        "People with a disability",
        "persons",
        "Civilian noninstitutionalized population",
        ("S1810_C02_001E",),
        ("S1810_C01_001E",),
    ),
    "rent_burden": PopulationVariables(
        "Renter households paying 30% or more of income on rent",
        "households",
        "Occupied units paying rent (excluding units where GRAPI cannot be computed)",
        ("DP04_0141E", "DP04_0142E"),
        ("DP04_0136E",),
    ),
    "below_200_percent_poverty": PopulationVariables(
        "Residents below 200% of the poverty threshold",
        "persons",
        _POVERTY_UNIVERSE,
        _cells("C17002", *range(2, 8)),
        _cells("C17002", 1),
    ),
    "below_poverty_no_snap": PopulationVariables(
        "Households below poverty reporting no SNAP",
        "households",
        "Households",
        _cells("B22003", 6),
        _cells("B22003", 3, 6),
    ),
}

# Acquire every cell, even if it appears in the baseline registry: the committed
# baseline database currently publishes only three indicators, not all 25 cells.
POPULATION_VARIABLES = tuple(
    sorted({v for p in POPULATIONS.values() for v in p.numerator + p.denominator})
)


def load_population_config(path: Path = Path("config.toml")) -> ACSConfig:
    """Extend a private Census configuration; baseline/SNAP consumers stay isolated."""
    config = load_config(path)
    labels = TypeAdapter(dict[str, str]).validate_python(
        tomllib.loads(path.read_text())["population_labels"], strict=True
    )
    return config.model_copy(update={"labels": config.labels | labels})


NATIVE_HAWAIIAN_ALONE = "B02016_002E"  # Verified too; never combined with B02019.
_ENDPOINTS: dict[str, Literal["profile", "subject"]] = {"DP": "profile", "S1": "subject"}


def verify_district_availability(client: CensusClient) -> int:
    """Check every cell, its MOE and annotations in all 51 House and 25 Senate districts.

    The client checks exact labels before any data request. Returns the number of
    district rows checked; raises CensusError on the first gap.
    """
    groups: dict[Literal["detailed", "profile", "subject"], list[str]] = {}
    for v in sorted({*POPULATION_VARIABLES, NATIVE_HAWAIIAN_ALONE}):
        groups.setdefault(_ENDPOINTS.get(v[:2], "detailed"), []).append(v)
    jobs = [
        (Indicator(tuple(cells[i : i + 12]), endpoint), chamber, count)
        for endpoint, cells in groups.items()
        for i in range(0, len(cells), 12)
        for chamber, count in (("lower", 51), ("upper", 25))
    ]

    def verify(job: tuple[Indicator, str, int]) -> int:
        group, chamber, count = job
        geography = f"state legislative district ({chamber} chamber)"
        rows = client.fetch(group, geography + ":*").rows
        if sorted(str(r.get(geography)) for r in rows) != [f"{n:03}" for n in range(1, count + 1)]:
            raise CensusError(f"District keys differ from 001-{count:03} ({chamber} chamber)")
        for row in rows:
            for column in (c for v in group.variables for c in (v, group.moe_variable(v))):
                value, note = row.get(column), row.get(column + "A")
                controlled = column.endswith("M") and (value, note) == ("-555555555", "*****")
                usable = note in (None, "") and (value or "").replace(".", "", 1).isdigit()
                if row.get("state") != "15" or not (controlled or usable):
                    where = f"{row.get(geography)} ({chamber} chamber)"
                    raise CensusError(f"{column} unavailable for district {where}")
        return len(rows)

    with ThreadPoolExecutor(max_workers=4) as executor:
        return sum(executor.map(verify, jobs))


if __name__ == "__main__":
    # Operator replay: CENSUS_API_KEY=... uv run python -m etl.population_variables
    config = load_population_config()
    client = CensusClient(config, api_key=os.environ.get("CENSUS_API_KEY"))
    print(f"ACS {config.vintage}: {verify_district_availability(client)} district rows verified")
