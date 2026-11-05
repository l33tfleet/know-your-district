"""Human-authored population registry (`data/populations.yaml`); validated, no observations.

Cells, units and universes follow the WO147 inventory in `etl/population_variables.py`
and `docs/data.md`. Every rule below fails loudly at load instead of guessing.
"""

import re
import unicodedata
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from yaml.nodes import MappingNode, Node, SequenceNode

from app.sources import Identifier, Text
from etl.population_variables import POPULATION_VARIABLES

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data/populations.yaml"

Unit = Literal["persons", "households"]
Period = Literal["survey_time", "past_12_months"]
Cell = Annotated[
    Text,
    StringConstraints(pattern=r"^(?:[BC][0-9]{5}_[0-9]{3}E|DP04_[0-9]{4}E|S1810_C0[12]_001E)$"),
]

_TOTAL = "Total population"
_POVERTY = "Population for whom poverty status is determined"
_HOUSEHOLDS = "Households"
_NHPI = "Native Hawaiian and Other Pacific Islander alone or in any combination"
_RENTERS = "Occupied units paying rent (excluding units where GRAPI cannot be computed)"

# Published table -> unit, universe and reference period of its cells.
TABLES: dict[str, tuple[Unit, str, Period]] = {
    "B01001": ("persons", _TOTAL, "survey_time"),
    "B02019": ("persons", _NHPI, "survey_time"),
    "B11005": ("households", _HOUSEHOLDS, "survey_time"),
    "B11007": ("households", _HOUSEHOLDS, "survey_time"),
    "B17001": ("persons", _POVERTY, "past_12_months"),
    "C17002": ("persons", _POVERTY, "past_12_months"),
    "B19055": ("households", _HOUSEHOLDS, "past_12_months"),
    "B19059": ("households", _HOUSEHOLDS, "past_12_months"),
    "B22003": ("households", _HOUSEHOLDS, "past_12_months"),
    "DP04": ("households", _RENTERS, "past_12_months"),
    "S1810": ("persons", "Civilian noninstitutionalized population", "survey_time"),
}
# A numerator universe that lies wholly inside a broader denominator universe.
_WITHIN = {_NHPI: _TOTAL}

# Overlapping income sources (docs/data.md): never summed, never "fixed income" or kūpuna.
_INCOME_SOURCES = {"B19055", "B19059"}
_FIXED_INCOME = re.compile(r"fixed\W*income", re.IGNORECASE)
_KUPUNA = re.compile(r"k[uū]puna", re.IGNORECASE)

_HAWAIIAN = ("Hawaiʻi", "Kauaʻi", "Lānaʻi", "Molokaʻi", "Oʻahu", "Kahoʻolawe", "Niʻihau", "Kūpuna")
# The ʻokina and the marks often typed in its place: apostrophe, left/right quote, grave.
_OKINA_LIKE = "\u02bb'\u2018\u2019`"
_WORD = re.compile(rf"[\w{_OKINA_LIKE}]+")


def _fold(word: str) -> str:
    bare = "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))
    return re.sub(f"[{_OKINA_LIKE}]", "", bare).lower()


_SPELLING = {_fold(word): word for word in _HAWAIIAN}


def _misspelled(text: str) -> list[str]:
    """Hawaiian place names and kūpuna written without the ʻokina or kahakō."""
    found: list[str] = []
    for word in _WORD.findall(text):
        correct = _SPELLING.get(_fold(word))
        if correct is not None and word.lower() != correct.lower():
            found.append(f"{word} (write {correct})")
    return found


class GeographyProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native: Literal["state legislative district"]
    plan: Literal[2022]
    allocation: Literal["none"]


class Population(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    label: Text
    unit: Unit
    universe: Text
    exclusions: Annotated[tuple[Text, ...], Field(min_length=1)]
    definition: Text
    numerator: Annotated[tuple[Cell, ...], Field(min_length=1)]
    denominator: Annotated[tuple[Cell, ...], Field(min_length=1)]
    period: Period
    geography: GeographyProvenance
    comparisons: Annotated[tuple[Literal["county", "state"], ...], Field(min_length=1)]

    @model_validator(mode="after")
    def compatible_cells(self) -> Self:
        if len(set(self.comparisons)) != len(self.comparisons):
            raise ValueError(f"{self.id}: comparisons repeat a geography")
        for side, cells in (("numerator", self.numerator), ("denominator", self.denominator)):
            if len(set(cells)) != len(cells):
                raise ValueError(f"{self.id}: {side} repeats a cell")
            for cell in cells:
                table = cell.split("_")[0]
                if cell not in POPULATION_VARIABLES or table not in TABLES:
                    raise ValueError(f"{self.id}: unknown variable {cell}")
                unit, universe, period = TABLES[table]
                if unit != self.unit:
                    raise ValueError(f"{self.id}: {cell} unit {unit} is not {self.unit}")
                nested = side == "numerator" and _WITHIN.get(universe) == self.universe
                if universe != self.universe and not nested:
                    raise ValueError(f"{self.id}: {cell} universe {universe!r} is incompatible")
                if period != self.period:
                    raise ValueError(f"{self.id}: {cell} period {period} is not {self.period}")
        tables = {c.split("_")[0] for c in self.numerator + self.denominator}
        if tables >= _INCOME_SOURCES:
            raise ValueError(f"{self.id}: B19055 and B19059 overlap and are never combined")
        if _FIXED_INCOME.search(self.label):
            raise ValueError(f"{self.id}: no published table measures fixed income")
        if tables & _INCOME_SOURCES and _KUPUNA.search(self.label):
            raise ValueError(f"{self.id}: household income counts are not kūpuna")
        texts = (self.label, self.universe, self.definition, *self.exclusions)
        if wrong := [w for text in texts for w in _misspelled(text)]:
            raise ValueError(f"{self.id}: Hawaiian spelling: {', '.join(wrong)}")
        return self


class PopulationRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["U.S. Census Bureau ACS 5-year"]
    vintage: Literal["2020–2024"]
    method: Literal["published estimate and 90% margin of error"]
    populations: Annotated[tuple[Population, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        seen: set[str] = set()
        for population in self.populations:
            if population.id in seen:
                raise ValueError(f"duplicate population id: {population.id}")
            seen.add(population.id)
        return self


def _unique_keys(node: Node) -> None:
    """Check before safe_load can silently overwrite human-authored mapping keys."""
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if key.value in keys:
                raise ValueError(f"duplicate YAML key: {key.value}")
            keys.add(key.value)
            _unique_keys(value)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _unique_keys(child)


def load_populations(path: Path = REGISTRY_PATH) -> PopulationRegistry:
    """Read and validate the registry, independently of the working directory."""
    content = path.read_text(encoding="utf-8")
    loader = yaml.SafeLoader(content)
    try:
        node = loader.get_single_node()
    finally:
        # PyYAML disposal returns None, but its upstream annotation is missing.
        loader.dispose()  # pyright: ignore[reportUnknownMemberType]
    if node is not None:
        _unique_keys(node)
    return PopulationRegistry.model_validate(yaml.safe_load(content))
