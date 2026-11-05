"""Logical indicator groups expanded into published scalar cells, never derived sums."""

from dataclasses import dataclass
from typing import Literal

from app.sources import load_source


@dataclass(frozen=True)
class Indicator:
    variables: tuple[str, ...]
    endpoint: Literal["detailed", "profile", "subject"]

    @property
    def table_id(self) -> str:
        return self.variables[0].split("_")[0]

    def moe_variable(self, variable: str) -> str:
        if variable not in self.variables:
            raise ValueError("Variable does not belong to indicator")
        return variable[:-1] + "M"


# Compatibility views for existing fetchers and the baseline build API.
BASELINE_SOURCE = load_source()
INDICATORS = {
    group.id: Indicator(tuple(variable.id for variable in group.variables), group.endpoint)
    for group in BASELINE_SOURCE.indicators
}
BUILD_INDICATORS = tuple(group.id for group in BASELINE_SOURCE.indicators if group.build)
