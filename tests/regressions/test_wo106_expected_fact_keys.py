"""WO106: complete boundary fact-key sets share the district identity contract."""

import pytest

from etl.boundaries import Chamber, all_districts, expected_fact_keys


@pytest.mark.parametrize("chamber,count", [("house", 51), ("senate", 25)])
def test_expected_chamber_fact_keys(chamber: Chamber, count: int) -> None:
    keys = expected_fact_keys(chamber)
    assert len(keys) == count
    assert keys == {district.fact_key for district in all_districts(chamber)}


def test_default_fact_keys_cover_both_chambers() -> None:
    house = expected_fact_keys("house")
    senate = expected_fact_keys("senate")
    keys = expected_fact_keys()
    assert len(keys) == 76
    assert keys == house | senate
    assert keys == expected_fact_keys("house", "senate")
    assert house.isdisjoint(senate)
