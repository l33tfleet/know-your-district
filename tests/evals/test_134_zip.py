"""ZIP traps: administrative cells cannot masquerade as ACS or district medians."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.zip_contract import CrosswalkRow, TaxObservation


def test_administrative_contract_has_no_acs_uncertainty_or_district_value() -> None:
    assert {"moe", "cv", "reliability", "district"}.isdisjoint(TaxObservation.model_fields)
    assert {"median", "value", "area_share"}.isdisjoint(CrosswalkRow.model_fields)
    with pytest.raises(ValidationError, match="zcta"):
        CrosswalkRow.model_validate(
            dict(
                district=dict(chamber="house", district=1),
                intersection_population=1,
                zcta_population=2,
                district_population=3,
                population_year=2020,
                method="population-weighted (2020 blocks)",
                source_url="https://www.census.gov/example",
                retrieved_on="2026-10-29",
            )
        )


def test_zip_traps_are_explicit_in_data_contract() -> None:
    contract = Path("docs/data.md").read_text()
    for warning in (
        "ZIP ≠ ZCTA",
        "administrative",
        "Medians are non-apportionable",
        "unmappable",
        "both population denominators",
    ):
        assert warning in contract
