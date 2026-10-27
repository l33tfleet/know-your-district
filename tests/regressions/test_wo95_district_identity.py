"""WO95: boundary identities and fact geographies share one district contract."""

import pytest
from pydantic import ValidationError

from etl.boundaries import DISTRICT_COUNTS, Chamber, DistrictId, all_districts
from etl.census import CensusBatch, CensusError
from etl.facts import facts_from_batch
from etl.indicators import INDICATORS


@pytest.mark.parametrize("chamber,count", [("house", 51), ("senate", 25)])
def test_complete_ordered_district_identities(chamber: Chamber, count: int) -> None:
    districts = list(all_districts(chamber))
    assert DISTRICT_COUNTS[chamber] == len(districts) == count
    assert [district.district for district in districts] == list(range(1, count + 1))
    assert [district.key for district in districts] == [
        f"{chamber}-{number:02d}" for number in range(1, count + 1)
    ]
    assert [district.census_code for district in districts] == [
        f"{number:03d}" for number in range(1, count + 1)
    ]
    keys = [district.fact_key for district in districts]
    assert keys == [f"{chamber}:15:{number:03d}:2022" for number in range(1, count + 1)]
    assert len(set(keys)) == count


def test_chambers_have_distinct_fact_keys() -> None:
    keys = [district.fact_key for chamber in DISTRICT_COUNTS for district in all_districts(chamber)]
    assert len(keys) == len(set(keys)) == 76


def _batch(column: str, count: int) -> CensusBatch:
    return CensusBatch(
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        vintage="2020–2024",
        labels={"B01003_001E": "Estimate!!Total"},
        rows=[
            {
                "state": "15",
                column: f"{number:03d}",
                "B01003_001E": "100",
                "B01003_001M": "10",
                "B01003_001EA": None,
                "B01003_001MA": None,
            }
            for number in range(1, count + 1)
        ],
    )


@pytest.mark.parametrize(
    "chamber,column,count",
    [
        ("house", "state legislative district (lower chamber)", 51),
        ("senate", "state legislative district (upper chamber)", 25),
    ],
)
def test_fact_keys_match_every_district(chamber: Chamber, column: str, count: int) -> None:
    batch = _batch(column, count)
    # Reversed source order ensures agreement is by identity, not row position.
    batch.rows.reverse()
    facts = facts_from_batch(INDICATORS["population"], batch, column + ":*")
    expected = {f"{chamber}:15:{number:03d}:2022" for number in range(1, count + 1)}
    actual = {fact.geography for fact in facts}
    assert len(facts) == count
    assert actual == expected == {district.fact_key for district in all_districts(chamber)}


@pytest.mark.parametrize("chamber,last", [("house", 51), ("senate", 25)])
def test_fact_key_normalization_preserves_serialized_properties(
    chamber: Chamber, last: int
) -> None:
    for number in (1, last):
        for raw in (number, str(number), f"{number:03d}"):
            district = DistrictId(chamber=chamber, district=raw)
            assert district.fact_key == f"{chamber}:15:{number:03d}:2022"
            assert district.model_dump(mode="json") == {"chamber": chamber, "district": number}


@pytest.mark.parametrize(
    "chamber,number,limit",
    [("house", 0, 51), ("house", 52, 51), ("senate", 0, 25), ("senate", 26, 25)],
)
def test_district_limits(chamber: Chamber, number: int, limit: int) -> None:
    with pytest.raises(ValidationError, match=rf"district must be in 1\.\.{limit} for its chamber"):
        DistrictId(chamber=chamber, district=number)


def test_invalid_chamber_remains_a_validation_error() -> None:
    with pytest.raises(ValidationError) as error:
        DistrictId.model_validate({"chamber": "county", "district": 1})
    assert [(item["loc"], item["type"]) for item in error.value.errors()] == [
        (("chamber",), "literal_error")
    ]


@pytest.mark.parametrize(
    "column,count",
    [
        ("state legislative district (lower chamber)", 51),
        ("state legislative district (upper chamber)", 25),
    ],
)
def test_unpadded_census_codes_are_rejected_before_normalization(column: str, count: int) -> None:
    batch = _batch(column, count)
    batch.rows[0][column] = "1"
    with pytest.raises(CensusError, match=r"^Unexpected Census geography identity$"):
        facts_from_batch(INDICATORS["population"], batch, column + ":*")
