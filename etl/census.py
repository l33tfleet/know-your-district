"""Fetch published ACS cells only after checking their configured meanings.

Rows remain raw strings/nulls (including sentinels and annotations). The later
fact-building step must interpret them before constructing any numeric Fact.
"""

import json
import tomllib
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel, TypeAdapter, ValidationError

from etl.indicators import INDICATORS, Indicator


class CensusError(RuntimeError):
    """Operator-safe failure: never includes request URLs, bodies or secrets."""


class ACSConfig(BaseModel):
    year: int
    vintage: str
    base_url: str
    state: str
    vintages: dict[str, str]
    labels: dict[str, str]


def load_config(path: Path = Path("config.toml")) -> ACSConfig:
    try:
        config = ACSConfig.model_validate(tomllib.loads(path.read_text())["acs"])
        if config.vintages.get(str(config.year)) != config.vintage:
            raise ValueError
        variables = {v for group in INDICATORS.values() for v in group.variables}
        if not variables <= config.labels.keys():
            raise ValueError
        for label in config.labels.values():
            if not label.format(year=config.year).strip():
                raise ValueError
        config.base_url.format(year=config.year)
    except (OSError, ValueError, KeyError, ValidationError):
        raise CensusError(
            "Invalid ACS configuration: check vintage and label expectations"
        ) from None
    return config


@dataclass(frozen=True)
class CensusBatch:
    endpoint: str
    vintage: str
    labels: dict[str, str]
    rows: list[dict[str, str | None]]


class CensusClient:
    def __init__(self, config: ACSConfig, *, api_key: str | None = None) -> None:
        self.config = config
        self._api_key = api_key

    def _get(self, url: str, params: dict[str, str]) -> object:
        if self._api_key:
            params = params | {"key": self._api_key}
        try:
            with urlopen(url + "?" + urlencode(params), timeout=30) as response:
                payload: object = json.loads(response.read())
        except (OSError, ValueError, HTTPException):
            # urllib errors may include the complete keyed URL; suppress chaining.
            raise CensusError("Census HTTP request failed or returned invalid JSON") from None
        return payload

    def fetch(self, indicator: Indicator, geography: str) -> CensusBatch:
        config = self.config
        endpoint = config.base_url.format(year=config.year).rstrip("/")
        if indicator.endpoint != "detailed":
            endpoint += f"/{indicator.endpoint}"
        labels: dict[str, str] = {}
        columns: list[str] = []
        for variable in indicator.variables:
            raw_metadata = self._get(f"{endpoint}/variables/{variable}.json", {})
            try:
                metadata = TypeAdapter(dict[str, object]).validate_python(raw_metadata, strict=True)
            except ValidationError:
                raise CensusError(f"Invalid metadata for {variable}") from None
            expected = config.labels[variable].format(year=config.year)
            if metadata.get("label") != expected:
                raise CensusError(f"Label mismatch for {variable} in ACS {config.year}")
            moe = indicator.moe_variable(variable)
            attributes = metadata.get("attributes")
            if not isinstance(attributes, str) or not {moe, variable + "A", moe + "A"} <= set(
                attributes.split(",")
            ):
                raise CensusError(f"Missing MOE or annotation metadata for {variable}")
            labels[variable] = expected
            columns.extend((variable, moe, variable + "A", moe + "A"))
        params = {"get": ",".join(columns), "for": geography}
        if not geography.startswith("state:"):
            params["in"] = f"state:{config.state}"
        raw_data = self._get(endpoint, params)
        try:
            payload = TypeAdapter(list[list[str | None]]).validate_python(raw_data, strict=True)
            header = TypeAdapter(list[str]).validate_python(payload[0], strict=True)
        except (ValidationError, IndexError):
            raise CensusError("Invalid Census data response") from None
        if len(payload) < 2:
            raise CensusError("Invalid Census data response")
        if len(set(header)) != len(header) or not set(columns) <= set(header):
            raise CensusError("Missing or invalid Census columns")
        rows: list[dict[str, str | None]] = []
        for row in payload[1:]:
            if len(row) != len(header):
                raise CensusError("Invalid Census data row")
            rows.append(dict(zip(header, row, strict=True)))
        return CensusBatch(endpoint, config.vintage, labels, rows)
