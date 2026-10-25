"""Independent ACS oracle. Usage: independent_oracle.py VARIABLE GEOGRAPHY CODE.

No ETL, application, or config imports: expectations are independently pinned
for ACS 2020–2024. CENSUS_API_KEY is read only from the environment.
"""

import argparse
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import TypeAdapter, ValidationError

BASE = "https://api.census.gov/data/2024/acs/acs5"
LABELS = {
    "B01003_001E": "Estimate!!Total",
    "DP05_0024PE": "Percent!!SEX AND AGE!!Total population!!65 years and over",
    "B19013_001E": "Estimate!!Median household income in the past 12 months (in 2024 inflation-adjusted dollars)",
    "S1701_C03_001E": "Estimate!!Percent below poverty level!!Population for whom poverty status is determined",
    "S1701_C03_010E": "Estimate!!Percent below poverty level!!Population for whom poverty status is determined!!AGE!!65 years and over",
    "S2301_C04_001E": "Estimate!!Unemployment rate!!Population 16 years and over",
    "B22010_002E": "Estimate!!Total:!!Household received Food Stamps/SNAP in the past 12 months:",
    "S2201_C04_001E": "Estimate!!Percent households receiving food stamps/SNAP!!Households",
    "B19055_002E": "Estimate!!Total:!!With Social Security income",
    "B19059_002E": "Estimate!!Total:!!With retirement income",
    "B25064_001E": "Estimate!!Median gross rent",
    "S2701_C05_001E": "Estimate!!Percent Uninsured!!Civilian noninstitutionalized population",
    "S1810_C03_001E": "Estimate!!Percent with a disability!!Total civilian noninstitutionalized population",
    "S1602_C04_001E": "Estimate!!Percent limited English-speaking households!!All households",
    "B08201_002E": "Estimate!!Total:!!No vehicle available",
}
for number, bracket in ((141, "30.0 to 34.9 percent"), (142, "35.0 percent or more")):
    LABELS[f"DP04_{number:04}PE"] = (
        "Percent!!GROSS RENT AS A PERCENTAGE OF HOUSEHOLD INCOME (GRAPI)!!"
        "Occupied units paying rent (excluding units where GRAPI cannot be computed)!!" + bracket
    )
for number, bracket in enumerate(
    (
        "",
        "Under .50",
        ".50 to .99",
        "1.00 to 1.24",
        "1.25 to 1.49",
        "1.50 to 1.84",
        "1.85 to 1.99",
        "2.00 and over",
    ),
    1,
):
    LABELS[f"C17002_{number:03}E"] = "Estimate!!Total:" + ("!!" + bracket if bracket else "")


class OracleError(RuntimeError):
    """Safe operator error with no Census body, URL or credentials."""


@dataclass(frozen=True)
class Observation:
    variable: str
    geography: str
    value: float | None
    moe: float | None
    label: str
    estimate_annotation: str | None
    moe_annotation: str | None
    source: str
    table_id: str
    method: str
    vintage: str = "2020–2024"


def request(url: str, params: dict[str, str]) -> object:
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        params = params | {"key": key}
    try:
        with urlopen(url + "?" + urlencode(params), timeout=30) as response:
            payload: object = json.loads(response.read())
        return payload
    except (OSError, ValueError, HTTPException):
        raise OracleError("Census request failed or returned invalid JSON") from None


def geography_key(geography: str, code: str) -> str:
    if geography == "state" and code == "15":
        return "state:15"
    if geography == "county" and code in {"001", "003", "007", "009"}:
        return f"county:15:{code}"
    for chamber, name, limit in (("house", "lower", 51), ("senate", "upper", 25)):
        if (
            geography == f"state legislative district ({name} chamber)"
            and re.fullmatch(r"[0-9]{3}", code)
            and 1 <= int(code) <= limit
        ):
            return f"{chamber}:15:{code}:2022"
    raise OracleError("Unsupported Hawaiʻi geography or code")


def numeric(raw: str | None) -> tuple[float | None, str]:
    if raw == "-333333333":
        return None, "not available: median in open-ended interval (top/bottom-coded)"
    if raw is None or raw in {"-666666666", "-999999999", "-888888888", "-555555555", "-222222222"}:
        return None, "controlled" if raw == "-555555555" else "not available"
    try:
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise OracleError("Invalid Census numeric cell") from None
    return value, "published"


def fetch(variable: str, geography: str, code: str) -> Observation:
    key = geography_key(geography, code)
    if variable not in LABELS:
        raise OracleError("Unsupported ACS variable")
    endpoint = BASE + (
        "/profile" if variable.startswith("DP") else "/subject" if variable.startswith("S") else ""
    )
    moe = variable[:-1] + "M"
    columns = [variable, moe, variable + "A", moe + "A"]
    try:
        metadata = TypeAdapter(dict[str, object]).validate_python(
            request(f"{endpoint}/variables/{variable}.json", {}), strict=True
        )
        attributes = metadata.get("attributes")
        if (
            metadata.get("label") != LABELS[variable]
            or not isinstance(attributes, str)
            or not set(columns[1:]) <= set(attributes.split(","))
        ):
            raise OracleError("Census metadata mismatch")
    except ValidationError:
        raise OracleError("Invalid Census metadata") from None
    params = {"get": ",".join(columns), "for": f"{geography}:{code}"}
    if geography != "state":
        params["in"] = "state:15"
    try:
        rows = TypeAdapter(list[list[str | None]]).validate_python(
            request(endpoint, params), strict=True
        )
        expected = columns + (["state"] if geography == "state" else ["state", geography])
        if (
            len(rows) != 2
            or len(rows[0]) != len(set(rows[0]))
            or set(rows[0]) != set(expected)
            or len(rows[1]) != len(rows[0])
        ):
            raise OracleError("Invalid Census response shape or columns")
        row = dict(zip(rows[0], rows[1], strict=True))
        if row["state"] != "15" or (geography != "state" and row[geography] != code):
            raise OracleError("Census geography mismatch")
        value, value_status = numeric(row[variable])
        margin, moe_status = numeric(row[moe])
        estimate_annotation, moe_annotation = row[variable + "A"], row[moe + "A"]
    except ValidationError:
        raise OracleError("Invalid Census data response") from None
    method = f"Published ACS cell; estimate {value_status}; 90% MOE {moe_status}"
    for name, annotation in (("estimate", estimate_annotation), ("MOE", moe_annotation)):
        if annotation:
            method += f"; {name} annotation: {annotation}"
    return Observation(
        variable,
        key,
        value,
        margin,
        LABELS[variable],
        estimate_annotation,
        moe_annotation,
        f"U.S. Census Bureau; {endpoint}",
        variable.split("_")[0],
        method,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variable")
    parser.add_argument("geography")
    parser.add_argument("code")
    args = parser.parse_args(argv)
    try:
        observation = fetch(args.variable, args.geography, args.code)
    except OracleError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(asdict(observation), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
