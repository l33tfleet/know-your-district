"""#181: recorded Ask decisions, checked row identities and shared MOE comparisons."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.reliability import classify
from app.copy import section_copy
from app.models import Fact
from etl.boundaries import DistrictId

DISTRICT = "house:15:022:2022"
COUNTY = "county:15:003"
STATE = "state:15"


def fact(
    geography: str,
    value: float | None,
    moe: float | None,
    variable: str = "B22003_006E",
    label: str = "Households below poverty reporting no SNAP",
) -> Fact:
    cv, flag = classify(
        None if value is None else Decimal(str(value)), None if moe is None else Decimal(str(moe))
    )
    return Fact(
        variable=variable,
        geography=geography,
        vintage="2020–2024",
        value=value,
        moe=moe,
        cv=None if cv is None else float(cv),
        reliability=flag,
        source="U.S. Census Bureau ACS 5-year",
        table_id=variable.split("_")[0],
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label=label,
    )


@pytest.mark.parametrize(
    "value,moe,state_value,state_moe,group",
    [
        (120, 2, 5100, 102, "higher"),
        (80, 2, 5100, 102, "lower"),
        (103, 2, 5100, 102, "higher"),
        (103.29, 2, 5100, 0, "higher"),
        (103.30, 2, 5100, 0, "higher"),
        (100, 0, 5100, 0, "indeterminate"),
        (120, 0, 5100, 0, "higher"),
        (80, 0, 5100, 0, "lower"),
        (120, 80, 5100, 102, "caution"),
        (120, 2, 5100, 3000, "caution"),
        (0, 2, 5100, 102, "caution"),
        (120, None, 5100, 102, "caution"),
        (120, 2, 5100, None, "caution"),
        (120, 2, 0, 102, "caution"),
        (None, 2, 5100, 102, "missing"),
        (120, 2, None, 102, "missing"),
        (105, 3, 5100, 204, "indeterminate"),  # equality: 5² = 3² + 4²
        (105.001, 3, 5100, 204, "higher"),
        (94.999, 3, 5100, 204, "lower"),
        (95, 3, 5100, 204, "indeterminate"),
    ],
)
def test_comparison_contract(
    value: float | None,
    moe: float | None,
    state_value: float | None,
    state_moe: float | None,
    group: str,
) -> None:
    from app.analysis.outreach import build_rows, compare_facts

    district = fact("house:15:001:2022", value, moe)
    state = fact(STATE, state_value, state_moe)
    result = build_rows("house", {(f.variable, f.geography): f for f in [district, state]}, [])
    row = result.rows[0]
    assert row.group == group
    assert row.fact == district
    assert row.reliability_word == section_copy("figures")["reliability"][district.reliability]
    assert row.comparison == section_copy("outreach")["groups"][group]
    assert compare_facts(district, result.state_basis) == group


def test_comparator_missing_and_vintage() -> None:
    from app.analysis.outreach import compare_facts

    a = fact(DISTRICT, 103, 2)
    assert compare_facts(a, fact(COUNTY, 100, 2)) == "higher"
    assert compare_facts(None, a) == compare_facts(a, None) == "missing"
    assert compare_facts(a, a.model_copy(update={"vintage": "2019–2023"})) == "missing"


def reference(f: Fact) -> dict[str, str]:
    return {k: getattr(f, k) for k in ("variable", "geography", "vintage")}


def render(record: dict[str, object], facts: list[Fact] | None = None) -> str:
    from app.agent.answers import AnswerRenderer, parse_answer

    return str(
        AnswerRenderer(DistrictId(chamber="house", district=22), facts or []).render(
            parse_answer(record)
        )
    )


def test_swapped_references_keep_their_own_population_and_geography() -> None:
    a = fact(DISTRICT, 123, 7)
    b = fact(COUNTY, 87654, 300, "B19013_001E", "Median household income")
    for refs in ([reference(a), reference(b)], [reference(b), reference(a)]):
        html = render(
            {"kind": "routed", "indicator_id": "population", "confidence": 0.9, "references": refs},
            [a, b],
        )
        assert (
            "Households below poverty reporting no SNAP · Hawaiʻi State House District 22: 123"
            in html
        )
        assert "Median household income · Honolulu County: $87,654" in html
        for f in (a, b):
            for value in (f.source, f.table_id, f.vintage, f.geography, f.method):
                assert value in html
        assert "±7" in html and "±$300" in html and "reliable" in html
        assert "Published for district" in html and "County/state context" in html


@pytest.mark.parametrize(
    "field,value",
    [
        ("prose", "There are 999 residents."),
        ("prose", "There are nine residents."),
        ("value", 999),
        ("label", "Eligible residents"),
    ],
)
def test_unsupported_prose_and_values_rejected(field: str, value: object) -> None:
    from app.agent.answers import parse_answer

    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse_answer(
            {"kind": "routed", "indicator_id": "population", "confidence": 0.9, field: value}
        )


@pytest.mark.parametrize(
    "change,error",
    [
        ({"geography": "house:15:021:2022"}, "outside page geographies"),
        ({"geography": "county:15:001"}, "outside page geographies"),
        ({"variable": "B01003_001E"}, "unknown fact reference"),
        ({"vintage": "2019–2023"}, "unknown fact reference"),
    ],
)
def test_reference_identity_and_scope(change: dict[str, str], error: str) -> None:
    a = fact(DISTRICT, 123, 7)
    ref = reference(a) | change
    foreign = a.model_copy(update=change)
    with pytest.raises(ValueError, match=error):
        render(
            {
                "kind": "routed",
                "indicator_id": "population",
                "confidence": 0.9,
                "references": [ref],
            },
            [a, foreign] if "geography" in change else [a],
        )


@pytest.mark.parametrize(
    "reason", ["individual", "partisan", "eligibility", "unsupported", "out_of_scope"]
)
def test_five_fixed_refusals(reason: str) -> None:
    assert render({"kind": "refuse", "reason": reason}) == section_copy("ask")["refusals"][reason]


def test_recorded_none_and_paused() -> None:
    assert (
        render({"kind": "routed", "indicator_id": "none", "confidence": 0.9})
        == section_copy("ask")["refusals"]["out_of_scope"]
    )
    assert render({"kind": "paused"}) == section_copy("ask")["paused"]


def test_clarifier_uses_top_probabilities_and_fixed_income_stays_separate() -> None:
    html = render(
        {
            "kind": "clarify",
            "reason": "fixed_income",
            "alternatives": [
                {"indicator_id": "retirement_households", "probability": 0.1},
                {"indicator_id": "social_security_households", "probability": 0.4},
                {"indicator_id": "older_living_alone", "probability": 0.2},
                {"indicator_id": "poverty_65_rate", "probability": 0.3},
            ],
        }
    )
    assert "No published measure defines fixed income" in html
    assert html.index("Social Security") < html.index("Poverty rate") < html.index("living alone")
    assert "<p>Households with retirement income</p>" not in html
    assert "overlap" in html


def test_kupuna_question_returns_share_only_and_unavailable_stays_unavailable() -> None:
    share = fact(DISTRICT, 21.3, 1.2, "DP05_0024PE", "Share of residents age 65 and over")
    html = render({"kind": "routed", "indicator_id": "age_65_share", "confidence": 0.95}, [share])
    assert "Share of residents age 65 and over" in html and "21.3%" in html
    assert "±1.2 percentage points" in html
    assert "never computed from the share" in html
    assert "not available" in html  # county/state absent, never imputed
    missing = render(
        {"kind": "routed", "indicator_id": "social_security_households", "confidence": 0.9}
    )
    assert "not available" in missing and "0 households" not in missing


@pytest.mark.parametrize(
    "income,group,word", [(103000, "higher", "Clearly higher"), (80000, "lower", "Clearly lower")]
)
def test_ask_uses_shared_comparator_and_whole_county_income(
    income: float, group: str, word: str
) -> None:
    from app.agent.answers import AnswerRenderer
    from app.analysis.outreach import compare_facts

    a = fact(DISTRICT, income, 2000, "B19013_001E", "Median household income")
    b = fact(COUNTY, 100000, 2000, a.variable, a.label)
    renderer = AnswerRenderer(DistrictId(chamber="house", district=22), [a, b])
    assert renderer.compare(reference(a), reference(b)) == compare_facts(a, b) == group
    html = render(
        {"kind": "routed", "indicator_id": "median_household_income", "confidence": 0.9}, [a, b]
    )
    assert "$100,000" in html and word in html
    with pytest.raises(ValueError, match="same variable"):
        renderer.compare(reference(a), reference(fact(COUNTY, 10, 1)))


def test_recorded_case_uses_existing_snap_card_first() -> None:
    from collections.abc import Callable
    from importlib import import_module
    from typing import cast

    from fastapi.templating import Jinja2Templates

    from app.page_state import PageState

    district = DistrictId(chamber="house", district=22)
    card = cast(
        Callable[[PageState, str], dict[str, object]],
        import_module("app.sections.15_case").case_card,
    )(PageState(district=district), "snap_no_receipt")
    templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")
    expected = templates.get_template("sections/15-case.html").render(
        section=card, copy=section_copy("case"), state=PageState(district=district)
    )
    html = render({"kind": "routed", "case_id": "snap_no_receipt", "confidence": 0.99})
    assert html.startswith(expected)
    assert "DHS decides eligibility" in html


@pytest.mark.parametrize(
    "record,error",
    [
        ({"kind": "routed", "indicator_id": "invented", "confidence": 0.9}, "Unknown indicator"),
        ({"kind": "routed", "case_id": "invented", "confidence": 0.9}, "Unknown case"),
        ({"kind": "routed", "confidence": 0.9}, "exactly one"),
        (
            {
                "kind": "routed",
                "case_id": "snap_no_receipt",
                "indicator_id": "population",
                "confidence": 0.9,
            },
            "exactly one",
        ),
        (
            {
                "kind": "clarify",
                "alternatives": [{"indicator_id": "population", "probability": 0.5}],
            },
            "at least 2",
        ),
        ({"kind": "refuse", "reason": "invented"}, "literal_error"),
        ({"kind": "routed", "indicator_id": "population", "confidence": 1.1}, "less_than_equal"),
    ],
)
def test_invalid_recorded_decisions(record: dict[str, object], error: str) -> None:
    from app.agent.answers import parse_answer

    with pytest.raises(ValueError, match=error):
        parse_answer(record)


def test_real_tool_rows_render_without_age_count_derivation() -> None:
    from app.agent.answers import AnswerRenderer, parse_answer
    from app.tools.facts import DistrictFacts

    district = DistrictId(chamber="house", district=22)
    tool = DistrictFacts(district)
    rows = [tool.get_facts(g, ["age_65_share"])["age_65_share"] for g in (DISTRICT, COUNTY, STATE)]
    html = str(
        AnswerRenderer(district, [f for f in rows if f is not None]).render(
            parse_answer({"kind": "routed", "indicator_id": "age_65_share", "confidence": 0.9})
        )
    )
    for row in rows:
        assert row is not None and row.value is not None
        assert f"{row.value:.1f}%" in html
        assert row.label in html
        assert row.geography in html
    assert "never computed from the share" in html


@pytest.mark.parametrize(
    "value,moe,word",
    [
        (None, None, "not available"),
        (0, 2, "use with caution"),
        (100, None, "use with caution"),
        (100, 40, "moderate: use with care"),
    ],
)
def test_unavailable_and_uncertain_rows_remain_visible(
    value: float | None, moe: float | None, word: str
) -> None:
    row = fact(DISTRICT, value, moe, "B19055_002E", "Households with Social Security income")
    html = render(
        {"kind": "routed", "indicator_id": "social_security_households", "confidence": 0.9}, [row]
    )
    assert word in html and row.label in html
    assert row.method in html and "Survey answers undercount benefit receipt" in html
    if moe is None:
        assert "no margin of error published" in html


def test_all_geography_labels_and_escaped_fact_labels() -> None:
    row = fact(DISTRICT, 103, 2, label="<script>untrusted</script>").model_copy(
        update={"method": "derived estimate from published cells"}
    )
    html = render(
        {"kind": "routed", "indicator_id": "below_poverty_no_snap", "confidence": 0.9}, [row]
    )
    assert "Estimated for district" in html
    assert "&lt;script&gt;untrusted&lt;/script&gt;" in html
    assert "<script>" not in html
    assert set(section_copy("ask")["geography_labels"].values()) == {
        "Published for district",
        "Estimated for district",
        "County/state context",
    }


def test_clarifier_with_two_options_case_and_none_uses_approved_copy() -> None:
    html = render(
        {
            "kind": "clarify",
            "alternatives": [
                {"indicator_id": "none", "probability": 0.3},
                {"case_id": "snap_no_receipt", "probability": 0.7},
            ],
        }
    )
    assert section_copy("ask")["clarify"] in html
    assert section_copy("snap")["heading"] in html
    assert section_copy("ask")["refusals"]["out_of_scope"] in html
    assert "0.7" not in html and "0.3" not in html


def test_duplicate_identity_and_unsupported_units_are_rejected() -> None:
    from app.agent.answers import AnswerRenderer

    a = fact(DISTRICT, 100, 2)
    district = DistrictId(chamber="house", district=22)
    with pytest.raises(ValueError, match="duplicate fact identity"):
        AnswerRenderer(district, [a, a])
    unsupported = fact(DISTRICT, 100, 2, "B99999_001E")
    with pytest.raises(ValueError, match="unsupported fact unit"):
        render(
            {
                "kind": "routed",
                "indicator_id": "population",
                "confidence": 0.9,
                "references": [reference(unsupported)],
            },
            [unsupported],
        )


def test_duplicate_clarifier_options_rejected() -> None:
    from app.agent.answers import parse_answer

    with pytest.raises(ValidationError, match="clarifier options must be distinct"):
        parse_answer(
            {
                "kind": "clarify",
                "alternatives": [
                    {"indicator_id": "population", "probability": 0.6},
                    {"indicator_id": "population", "probability": 0.4},
                ],
            }
        )


@pytest.mark.parametrize(
    "geography", ["house:15:022:2022?x=1", "../state:15", "state:15%2e", "state:15\n"]
)
def test_untrusted_reference_identifiers_rejected(geography: str) -> None:
    from app.agent.answers import parse_answer

    with pytest.raises(ValidationError):
        parse_answer(
            {
                "kind": "routed",
                "indicator_id": "population",
                "confidence": 0.9,
                "references": [
                    {"variable": "B01003_001E", "geography": geography, "vintage": "2020–2024"}
                ],
            }
        )
