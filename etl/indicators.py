"""Logical indicator groups expanded into published scalar cells, never derived sums."""

from dataclasses import dataclass
from typing import Literal


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


INDICATORS = {
    "population": Indicator(("B01003_001E",), "detailed"),
    "age_65_share": Indicator(("DP05_0024PE",), "profile"),
    "median_household_income": Indicator(("B19013_001E",), "detailed"),
    "poverty_rate": Indicator(("S1701_C03_001E",), "subject"),
    "poverty_65_rate": Indicator(("S1701_C03_010E",), "subject"),
    "unemployment_rate": Indicator(("S2301_C04_001E",), "subject"),
    "snap_households": Indicator(("B22010_002E",), "detailed"),
    "snap_share": Indicator(("S2201_C04_001E",), "subject"),
    "social_security_households": Indicator(("B19055_002E",), "detailed"),
    "retirement_households": Indicator(("B19059_002E",), "detailed"),
    "rent_burden": Indicator(("DP04_0141PE", "DP04_0142PE"), "profile"),
    "median_gross_rent": Indicator(("B25064_001E",), "detailed"),
    "uninsured_rate": Indicator(("S2701_C05_001E",), "subject"),
    "disability_share": Indicator(("S1810_C03_001E",), "subject"),
    "limited_english_share": Indicator(("S1602_C04_001E",), "subject"),
    "no_vehicle_households": Indicator(("B08201_002E",), "detailed"),
    "poverty_ratio": Indicator(tuple(f"C17002_{i:03}E" for i in range(1, 9)), "detailed"),
}
