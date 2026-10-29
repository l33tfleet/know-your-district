"""WO261 step 1 (#282): pure comparison and figure-sentence helpers for the sentence brief.

`compare()` is #30's reviewed rule (|a-b| / sqrt(MOEa² + MOEb²) > 1.645, strict, in Decimal);
caution and vintage mismatch short-circuit before any arithmetic. Population is never compared;
the share 65+ and median household income are. The comparison dict carries the reference
figure's value and MOE unchanged from the Fact, so no number is written by a model.
"""

import re

import pytest

from app.analysis.compare import compare
from app.brief_facts import FORMATS, KINDS, STATE, comparison
from app.copy import section_copy
from app.models import Fact

DISTRICT = "house:15:043:2022"
VINTAGE = "2020–2024"


def fact(
    value: float | None,
    moe: float | None,
    geography: str = DISTRICT,
    vintage: str = VINTAGE,
    variable: str = "DP05_0024PE",
) -> Fact:
    if value is None:
        cv, reliability = None, "unavailable"
    elif value == 0 or moe is None:
        cv, reliability = None, "caution"
    else:
        cv = moe / 1.645 / value
        reliability = "reliable" if cv <= 0.15 else "moderate" if cv <= 0.30 else "caution"
    return Fact(
        variable=variable,
        geography=geography,
        vintage=vintage,
        value=value,
        moe=moe,
        cv=cv,
        reliability=reliability,
        source="U.S. Census Bureau ACS 5-year",
        table_id=variable.split("_")[0],
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label="Estimate!!Total",
    )


def test_strict_boundary_is_indeterminate_and_just_past_is_a_difference() -> None:
    # |a-b| = 1.645 * sqrt(3² + 4²) = 8.225 exactly: equal to the bound is not a difference.
    assert compare(fact(100.0, 3.0), fact(108.225, 4.0, STATE)) == "indeterminate"
    assert compare(fact(108.225, 3.0), fact(100.0, 4.0, STATE)) == "indeterminate"
    assert compare(fact(100.0, 3.0), fact(108.226, 4.0, STATE)) == "lower"
    assert compare(fact(108.226, 3.0), fact(100.0, 4.0, STATE)) == "higher"


def test_zero_moe_on_both_sides() -> None:
    assert compare(fact(50.0, 0.0), fact(50.0, 0.0, STATE)) == "indeterminate"
    assert compare(fact(50.1, 0.0), fact(50.0, 0.0, STATE)) == "higher"
    assert compare(fact(49.9, 0.0), fact(50.0, 0.0, STATE)) == "lower"


def test_caution_short_circuits_before_arithmetic() -> None:
    caution = fact(10.0, 9.0)
    assert caution.reliability == "caution"
    assert compare(caution, fact(90.0, 1.0, STATE)) == "caution"
    assert compare(fact(90.0, 1.0), fact(10.0, 9.0, STATE)) == "caution"
    # A zero estimate is caution (no CV), never a difference.
    assert compare(fact(0.0, 5.0), fact(90.0, 1.0, STATE)) == "caution"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (None, fact(10.0, 1.0, STATE)),
        (fact(10.0, 1.0), None),
        (fact(None, None), fact(10.0, 1.0, STATE)),
        (fact(10.0, 1.0), fact(None, None, STATE)),
        (fact(10.0, 1.0), fact(90.0, 1.0, STATE, vintage="2019–2023")),
    ],
)
def test_missing_short_circuits(a: Fact | None, b: Fact | None) -> None:
    assert compare(a, b) == "missing"


def test_missing_wins_over_caution() -> None:
    assert compare(fact(10.0, 9.0), fact(90.0, 1.0, STATE, vintage="2019–2023")) == "missing"


def test_kinds_cover_every_figure() -> None:
    assert set(KINDS) == set(FORMATS)
    assert KINDS["population"].kind == "count" and not KINDS["population"].compared
    assert KINDS["age_65_share"].kind == "share" and KINDS["age_65_share"].compared
    assert KINDS["age_65_share"].companion_count is None
    assert KINDS["median_household_income"].kind == "dollars"
    assert KINDS["median_household_income"].compared


def test_population_never_gets_a_comparison() -> None:
    copy = section_copy("figures")
    district = fact(10000.0, 10.0, variable="DP05_0001E")
    state = fact(1.4e6, 0.0, STATE, variable="DP05_0001E")
    assert comparison(district, state, FORMATS["population"], copy, figure="population") is None


@pytest.mark.parametrize(
    ("figure", "district", "reference", "group"),
    [
        ("age_65_share", fact(30.0, 1.0), fact(20.0, 0.2, STATE), "higher"),
        ("age_65_share", fact(10.0, 1.0), fact(20.0, 0.2, STATE), "lower"),
        ("age_65_share", fact(20.5, 1.0), fact(20.0, 0.2, STATE), "indeterminate"),
        ("age_65_share", fact(10.0, 9.0), fact(20.0, 0.2, STATE), "caution"),
        ("age_65_share", None, fact(20.0, 0.2, STATE), "missing"),
        ("median_household_income", fact(120000.0, 5000.0), fact(95000.0, 800.0, STATE), "higher"),
        ("median_household_income", fact(60000.0, 5000.0), fact(95000.0, 800.0, STATE), "lower"),
        (
            "median_household_income",
            fact(94000.0, 5000.0),
            fact(95000.0, 800.0, STATE),
            "indeterminate",
        ),
    ],
)
def test_share_and_median_get_a_worded_comparison(
    figure: str, district: Fact | None, reference: Fact, group: str
) -> None:
    copy = section_copy("figures")
    result = comparison(district, reference, FORMATS[figure], copy, figure=figure)
    assert result is not None
    assert result["group"] == group
    words = copy["comparisons"][KINDS[figure].kind][group]
    assert result["clause"] == words["lead"]
    assert result["tail"] == words.get("tail", "")
    # The reference reading carries the Fact's own numbers, unchanged.
    ref = result["reference"]
    assert isinstance(ref, dict)
    assert ref["value"] == reference.value
    assert ref["moe"] == reference.moe
    assert ref["geography"] == reference.geography
    assert ref["moe_text"] == "±" + FORMATS[figure](reference.moe or 0.0)


def test_missing_reference_keeps_its_geography() -> None:
    copy = section_copy("figures")
    result = comparison(fact(20.0, 1.0), None, FORMATS["age_65_share"], copy, figure="age_65_share")
    assert result is not None and result["group"] == "missing"
    ref = result["reference"]
    assert isinstance(ref, dict)
    assert ref["geography"] == STATE and ref["found"] is False


def figures_in(text: str) -> list[str]:
    """Digits in copy, other than the "65" that names the age group."""
    return re.findall(r"\d+", text.replace("age 65", "age"))


def test_comparison_copy_has_every_group_and_no_numbers() -> None:
    copy = section_copy("figures")
    for kind in {k.kind for k in KINDS.values() if k.compared}:
        groups = copy["comparisons"][kind]
        assert set(groups) == {"higher", "lower", "indeterminate", "caution", "missing"}
        for words in groups.values():
            for text in words.values():
                assert not figures_in(text), text
    for key in ("count_sentence", "share_sentence", "dollars_sentence", "count_unavailable"):
        assert not figures_in(copy[key]), key
    assert "share" in copy["comparisons"]["share"]["higher"]["lead"]
    assert "margins of error" in copy["comparisons"]["share"]["indeterminate"]["tail"]
    assert "no comparison claim" in copy["comparisons"]["share"]["caution"]["lead"]
