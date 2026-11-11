"""WO260: a controlled MOE reads as a controlled total, never "use with caution".

Census controls county and state total population to the official population
estimates, so it publishes no sampling margin for them (MOE `-555555555`, annotation
`*****`). The ETL keeps the stored reliability `caution` and records the status in the
method as the clause `MOE controlled`. The brief now words that figure as a controlled
total beside the value and in its source details; a genuinely missing MOE still says
"use with caution", and a missing estimate is still "not available".

Replaces, for the new spec, `test_wo97_brief_page.py::test_each_figure_equals_the_fixture_rows`
(already carried by `test_wo187_figure_sentences.py`): both district cases, every value,
MOE, citation, source-details and ordinary reliability check are kept; only the
controlled state total's expected wording changes, and a missing-MOE case is added.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.reliability import FLAG_WORDS, controlled_moe
from app.brief_facts import FORMATS, citation, reading
from app.copy import section_copy
from app.facts import FactStore, acs_config
from app.main import app
from app.models import Fact
from tests.regressions.test_wo97_brief_page import (
    HOUSE_22,
    ROWS,
    SENATE_5,
    STATE,
    VARIABLES,
    Node,
    brief,
    build_db,
    check_citation,
    row,
)
from tests.regressions.test_wo187_method_notes import _fact  # pyright: ignore[reportPrivateUsage]
from tests.regressions.test_wo261_figure_sentences import (
    COUNTY_ROWS,
    MOE_TEXT,
    VALUE_TEXT,
    sentence,
)

COPY = section_copy("figures")
CAUTION = FLAG_WORDS["caution"]
# The method the ETL writes for a controlled MOE (etl/facts.py, METHOD_SEPARATOR ". ").
CONTROLLED_METHOD = (
    "published estimate and 90% margin of error. MOE controlled. MOE annotation: *****"
)
MISSING_METHOD = "published estimate and 90% margin of error. MOE not available. MOE annotation: N"


def with_method(fact: Fact, method: str) -> Fact:
    return fact.model_copy(update={"method": method})


# The state total is controlled; Honolulu County's median has a genuinely missing MOE.
STATE_TOTAL = with_method(row("population", STATE, 1446146.0, None), CONTROLLED_METHOD)
MISSING_MOE = with_method(
    row("median_household_income", "county:15:003", 92600.0, None), MISSING_METHOD
)
FIXTURE = [
    STATE_TOTAL if (r.variable, r.geography) == ("B01003_001E", STATE) else r for r in ROWS
] + [
    MISSING_MOE if r.variable == "B19013_001E" and r.geography == "county:15:003" else r
    for r in COUNTY_ROWS
]
COUNTY = {HOUSE_22: "county:15:003", SENATE_5: "county:15:009"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "facts.db"
    build_db(path, FIXTURE)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return TestClient(app)


def fixture_row(figure: str, geography: str) -> Fact | None:
    variable = VARIABLES[figure][0]
    return next((r for r in FIXTURE if (r.variable, r.geography) == (variable, geography)), None)


def is_controlled(fact: Fact) -> bool:
    return fact.moe is None and fact.value is not None and "MOE controlled." in fact.method


# --- the predicate ---------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["", ".0"])
def test_etl_controlled_sentinel_is_controlled(suffix: str) -> None:
    fact = _fact("1446146", "-555555555" + suffix)
    assert fact.moe is None and fact.reliability == "caution" and fact.cv is None
    assert controlled_moe(
        Decimal(repr(fact.value)) if fact.value is not None else None, None, fact.method
    )


@pytest.mark.parametrize("code", ["-666666666", "-999999999", "-888888888", "-222222222"])
def test_etl_missing_moe_sentinels_are_not_controlled(code: str) -> None:
    fact = _fact("1446146", code)
    assert fact.moe is None and fact.reliability == "caution"
    assert not controlled_moe(Decimal("1446146"), None, fact.method)


@pytest.mark.parametrize(
    ("value", "moe", "method", "expected"),
    [
        (Decimal(5), None, CONTROLLED_METHOD, True),
        (Decimal(5), None, "published estimate and 90% margin of error. MOE controlled", True),
        # A missing estimate takes precedence: it stays "not available".
        (None, None, CONTROLLED_METHOD, False),
        (None, None, "x. estimate not available. MOE controlled", False),
        # A published numeric MOE is never controlled wording.
        (Decimal(5), Decimal(0), CONTROLLED_METHOD, False),
        (Decimal(5), Decimal(3), CONTROLLED_METHOD, False),
        # A missing MOE without the exact clause keeps caution.
        (Decimal(5), None, MISSING_METHOD, False),
        (Decimal(5), None, "published estimate and 90% margin of error", False),
        (Decimal(5), None, "x. MOE uncontrolled", False),
        (Decimal(5), None, "x. MOE controlled by hand", False),
        (Decimal(5), None, "x. estimate controlled", False),
        (Decimal(5), None, "x. MOE annotation: MOE controlled note", False),
    ],
)
def test_controlled_needs_an_estimate_no_moe_and_the_exact_clause(
    value: Decimal | None, moe: Decimal | None, method: str, expected: bool
) -> None:
    assert controlled_moe(value, moe, method) is expected


def test_reading_and_citation_word_controlled_and_missing_apart() -> None:
    fmt = FORMATS["population"]
    controlled = reading(STATE, STATE_TOTAL, fmt, COPY)
    assert controlled["word"] == COPY["controlled"]
    assert controlled["word"] != CAUTION
    assert controlled["reliability"] == "caution"  # stored flag unchanged
    assert controlled["moe_text"] == COPY["controlled_total"]
    assert citation(STATE_TOTAL, fmt, COPY)["moe_text"] == COPY["controlled_moe"]
    missing = reading("county:15:003", MISSING_MOE, fmt, COPY)
    assert missing["word"] == CAUTION
    assert citation(MISSING_MOE, fmt, COPY)["moe_text"] == COPY["no_moe"]
    unavailable = with_method(row("population", STATE, None, None), CONTROLLED_METHOD)
    assert reading(STATE, unavailable, fmt, COPY)["word"] == FLAG_WORDS["unavailable"]


def test_controlled_wording_is_plain_and_never_caution() -> None:
    beside = f"{COPY['controlled_total']}, {COPY['controlled']}"
    for text in (beside, COPY["controlled_moe"]):
        assert "controlled total" in text and "no sampling error" in text
        assert "caution" not in text.lower()
    # The reliability mapping still names exactly the four stored flags.
    assert set(COPY["reliability"]) == set(FLAG_WORDS)


# --- the brief, both districts ---------------------------------------------------------


def check_span(span: Node, fact: Fact | None, figure: str) -> None:
    word = span.one(class_="reliability")
    if fact is None:
        assert span.find_all("data") == []
        assert span.one(class_="missing").text == COPY["no_row"]
        assert word.attrs["data-reliability"] == "unavailable"
        assert word.text == FLAG_WORDS["unavailable"]
        return
    value = span.one("data", class_="value")
    assert value.attrs["data-geography"] == fact.geography
    moe = span.one("span", class_="moe").one("data")
    if fact.value is None:
        assert value.attrs["value"] == "" and value.text == COPY["not_available"]
    else:
        assert float(value.attrs["value"]) == fact.value
        assert value.text == VALUE_TEXT[figure](fact.value)
    if fact.moe is None:
        assert moe.attrs["value"] == ""
        assert moe.text == (COPY["controlled_total"] if is_controlled(fact) else COPY["no_moe"])
    else:
        assert float(moe.attrs["value"]) == fact.moe
        assert moe.text == MOE_TEXT[figure](fact.moe)
    assert word.attrs["data-reliability"] == fact.reliability
    if is_controlled(fact):
        assert word.text == COPY["controlled"]
    else:
        assert word.text == FLAG_WORDS[fact.reliability]


@pytest.mark.parametrize(
    ("path", "district"), [("/brief/house/22", HOUSE_22), ("/brief/senate/5", SENATE_5)]
)
def test_each_figure_equals_the_fixture_rows_with_controlled_wording(
    client: TestClient, path: str, district: str
) -> None:
    page = brief(client, path)
    figures = page.find_all("div", class_="figure")
    assert [f.attrs["data-figure"] for f in figures] == list(VARIABLES)
    for node in figures:
        figure = node.attrs["data-figure"]
        shown = (district, COUNTY[district], STATE)
        spans = sentence(node).find_all("span", class_="reading")
        assert [s.attrs["data-geography"] for s in spans] == list(shown)
        for geography, span in zip(shown, spans, strict=True):
            check_span(span, fixture_row(figure, geography), figure)
        citations = node.one("details").find_all("dl", class_="citation")
        expected = [r for g in shown if (r := fixture_row(figure, g)) is not None]
        assert [c.attrs["data-geography"] for c in citations] == [r.geography for r in expected]
        for dl, fact in zip(citations, expected, strict=True):
            check_citation(dl, fact)
            moe_text = dl.one(data_field="moe").text
            if is_controlled(fact):
                assert moe_text == COPY["controlled_moe"]
            elif fact.moe is None:
                assert moe_text == COPY["no_moe"]


def test_state_b01003_total_shows_controlled_wording_never_caution(client: TestClient) -> None:
    for path in ("/brief/house/22", "/brief/senate/5"):
        node = brief(client, path).one("div", class_="figure", data_figure="population")
        state = sentence(node).one("span", class_="reading", data_geography=STATE)
        word = state.one(class_="reliability")
        assert word.text == COPY["controlled"]
        assert state.one("span", class_="moe").text == COPY["controlled_total"]
        assert CAUTION not in state.text
        dl = node.one("dl", data_geography=STATE)
        assert dl.one(data_field="table_id").text == "B01003"
        assert dl.one(data_field="moe").text == COPY["controlled_moe"]
        assert CAUTION not in dl.text


def test_missing_moe_still_shows_caution(client: TestClient) -> None:
    node = brief(client, "/brief/house/22").one(
        "div", class_="figure", data_figure="median_household_income"
    )
    county = sentence(node).one("span", class_="reading", data_geography="county:15:003")
    assert county.one(class_="reliability").text == CAUTION
    assert county.one("span", class_="moe").text == COPY["no_moe"]
    assert COPY["controlled_total"] not in node.text
    dl = node.one("dl", data_geography="county:15:003")
    assert dl.one(data_field="moe").text == COPY["no_moe"]


def test_committed_state_b01003_total_shows_controlled_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KYD_FACTS_DB", raising=False)
    vintage, _ = acs_config()
    fact = FactStore.default().get([("B01003_001E", STATE)], vintage)[("B01003_001E", STATE)]
    assert fact.moe is None and fact.reliability == "caution" and "MOE controlled" in fact.method
    node = brief(TestClient(app), "/brief/house/22").one(
        "div", class_="figure", data_figure="population"
    )
    state = sentence(node).one("span", class_="reading", data_geography=STATE)
    assert state.one(class_="reliability").text == COPY["controlled"]
    assert node.one("dl", data_geography=STATE).one(data_field="moe").text == COPY["controlled_moe"]
