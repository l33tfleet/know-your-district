"""Validated, committed district/county area overlay; no runtime network access."""

import csv
import math
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from etl.boundaries import expected_fact_keys

MAPPING_PATH = Path(__file__).resolve().parents[1] / "data/district_counties.tsv"


class CountyShare(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district: str
    county: str
    area_share: float = Field(gt=0, le=1, allow_inf_nan=False)
    district_source: str
    county_source: str
    vintage: str
    method: str


def load_mapping(path: Path | None = None) -> dict[str, list[CountyShare]]:
    """Reject partial maps, excluded counties, duplicate pairs and invalid area totals."""
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "config.toml").read_text())
    allowed = {f"county:15:{code}" for code in config["acs"]["county_codes"]}
    result: dict[str, list[CountyShare]] = {}
    with (MAPPING_PATH if path is None else path).open(encoding="utf-8", newline="") as stream:
        for record in csv.DictReader(stream, delimiter="\t"):
            share = CountyShare.model_validate(record)
            if share.county not in allowed:
                raise ValueError(f"excluded or unknown county: {share.county}")
            group = result.setdefault(share.district, [])
            if any(s.county == share.county for s in group):
                raise ValueError(f"duplicate district/county: {share.district} {share.county}")
            group.append(share)
    expected = expected_fact_keys()
    if result.keys() != expected:
        raise ValueError(
            f"district set mismatch: missing={sorted(expected - result.keys())}, extra={sorted(result.keys() - expected)}"
        )
    for district, shares in result.items():
        if not math.isclose(sum(s.area_share for s in shares), 1, abs_tol=1e-9):
            raise ValueError(f"area shares must sum to one: {district}")
    return result
