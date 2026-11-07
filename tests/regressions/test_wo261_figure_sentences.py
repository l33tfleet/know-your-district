"""WO261 step 3 (#284): each figure reads as one cited sentence suited to its unit.

One `<p class="reading" data-figure-sentence>` per figure (its class stays exactly `reading`,
which `test_wo261_strip_removed.py`'s House 43 test matches whole, so the sentence is marked by
the attribute rather than a second class). Inside it every geography shown is a
`<span class="reading" data-geography>` holding the `<data class="value">`, the `<span
class="moe">` and the `.reliability[data-reliability]` word (rules 1-2). Population shows the
district, county and state counts with no comparison words (the #284 Decision); the share 65+
and the median compare the district with each county and the state through `comparison()`,
and indeterminate, caution or missing groups make no larger/smaller claim. The share 65+ says
that the count of residents 65+ is not published; it is never computed from the share.

Replaces, for the new spec: `test_wo97_brief_page.py::test_each_figure_equals_the_fixture_rows`,
`::test_reliability_word_is_always_shown_including_caution`, `::test_no_comparison_words_yet`,
`test_wo121_counties.py::test_county_values_moes_and_citations_beside_state`,
`test_wo261_strip_removed.py::test_two_county_fixture_has_readings_and_citations_but_no_strip`
and `test_wo261_browser.py::test_house_43_renders_figures_without_any_strip`.
"""

import csv
import re
from collections.abc import Callable
from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

import app.counties as counties
from app.analysis.reliability import FLAG_WORDS
from app.brief_facts import KINDS, Kind
from app.copy import section_copy
from app.counties import load_mapping
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
    parse,
    row,
)
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page, page

# Reuse the WO122 server and Chromium fixtures without modifying their source.
__all__ = ["base_url", "browser", "page"]

ROOT = Path(__file__).resolve().parents[2]
HONOLULU = "county:15:003"
MAUI = "county:15:009"
COUNTY = {HOUSE_22: HONOLULU, SENATE_5: MAUI}
# Synthetic county rows; Maui County has no median row at all (copy.no_row).
COUNTY_ROWS = [
    row("population", HONOLULU, 1016508.0, 120.0),
    row("age_65_share", HONOLULU, 15.0, 0.3),  # House 22 (21.3 ± 2.1) is a real difference
    row("median_household_income", HONOLULU, 92600.0, 700.0),
    row("population", MAUI, 164000.0, 50.0),
    row("age_65_share", MAUI, 21.0, 0.5),
]
ALL_ROWS = [*ROWS, *COUNTY_ROWS]
CLAIMS = re.compile(r"\b(larger|smaller|higher|lower|above|below|more|fewer|less)\b")
MOE_TEXT: dict[str, Callable[[float], str]] = {
    "population": lambda m: f"±{m:,.0f}",
    "age_65_share": lambda m: f"±{m:.1f} points",
    "median_household_income": lambda m: f"±${m:,.0f}",
}
VALUE_TEXT: dict[str, Callable[[float], str]] = {
    "population": lambda v: f"{v:,.0f}",
    "age_65_share": lambda v: f"{v:.1f}%",
    "median_household_income": lambda v: f"${v:,.0f}",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "facts.db"
    build_db(path, ALL_ROWS)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return TestClient(app)


def fixture_row(figure: str, geography: str, rows: list[Fact] = ALL_ROWS) -> Fact | None:
    variable = VARIABLES[figure][0]
    return next((r for r in rows if r.variable == variable and r.geography == geography), None)


def sentence(figure: Node) -> Node:
    """The figure's one sentence."""
    found = figure.find_all("p", class_="reading", data_figure_sentence="")
    assert len(found) == 1, figure.attrs
    assert "data-geography" not in found[0].attrs
    return found[0]


def check_span(span: Node, fact: Fact | None, figure: str) -> None:
    """One reading inside the sentence equals its fixture row, or says the row is missing."""
    word = span.one(class_="reliability")
    if fact is None:
        assert span.find_all("data") == []
        assert span.one(class_="missing").text == section_copy("figures")["no_row"]
        assert word.attrs["data-reliability"] == "unavailable"
        assert word.text == FLAG_WORDS["unavailable"]
        return
    value = span.one("data", class_="value")
    assert value.attrs["data-geography"] == fact.geography
    moe = span.one("span", class_="moe").one("data")
    if fact.value is None:
        assert value.attrs["value"] == "" and value.text == "not available"
    else:
        assert float(value.attrs["value"]) == fact.value
        assert value.text == VALUE_TEXT[figure](fact.value)
    if fact.moe is None:
        assert moe.attrs["value"] == ""
        assert moe.text == "no margin of error published"
    else:
        assert float(moe.attrs["value"]) == fact.moe
        assert moe.text == MOE_TEXT[figure](fact.moe)
    assert word.attrs["data-reliability"] == fact.reliability
    assert word.text == FLAG_WORDS[fact.reliability]


@pytest.mark.parametrize(
    ("path", "district"), [("/brief/house/22", HOUSE_22), ("/brief/senate/5", SENATE_5)]
)
def test_each_figure_is_one_sentence_whose_values_and_citations_equal_the_rows(
    client: TestClient, path: str, district: str
) -> None:
    page = brief(client, path)
    figures = page.find_all("div", class_="figure")
    assert [f.attrs["data-figure"] for f in figures] == list(VARIABLES)
    assert len(page.find_all("p", class_="reading", data_figure_sentence="")) == 3
    for node in figures:
        figure = node.attrs["data-figure"]
        text = sentence(node)
        shown = (district, COUNTY[district], STATE)
        spans = text.find_all("span", class_="reading")
        assert [s.attrs["data-geography"] for s in spans] == list(shown)
        # Every number in the sentence sits in a reading of a shown geography.
        assert len(text.find_all("data", class_="value")) == sum(
            fixture_row(figure, g) is not None for g in shown
        )
        for geography, span in zip(shown, spans, strict=True):
            check_span(span, fixture_row(figure, geography), figure)
        citations = node.one("details").find_all("dl", class_="citation")
        expected = [r for g in shown if (r := fixture_row(figure, g)) is not None]
        assert [c.attrs["data-geography"] for c in citations] == [r.geography for r in expected]
        for dl, fact in zip(citations, expected, strict=True):
            check_citation(dl, fact)


def test_reliability_is_shown_on_every_reading_including_caution_and_unavailable(
    client: TestClient,
) -> None:
    page = brief(client, "/brief/senate/5")
    words: list[str] = []
    for node in page.find_all("div", class_="figure"):
        for span in sentence(node).find_all("span", class_="reading"):
            word = span.one(class_="reliability")
            assert word.text
            words.append(word.attrs["data-reliability"])
    assert len(words) == 9
    assert {"reliable", "caution", "unavailable"} <= set(words)


@pytest.mark.parametrize("path", ["/brief/house/22", "/brief/senate/5"])
def test_population_shows_district_county_and_state_counts_without_comparison(
    client: TestClient, path: str
) -> None:
    node = brief(client, path).one("div", class_="figure", data_figure="population")
    text = sentence(node)
    assert len(text.find_all("data", class_="value")) == 3
    assert "residents" in text.text
    assert not CLAIMS.search(text.text.lower()), text.text
    for word in ("than", "about the same", "margins of error", "comparison"):
        assert word not in text.text.lower()


def test_share_says_the_count_is_unavailable_and_never_computes_it(client: TestClient) -> None:
    page = brief(client, "/brief/house/22")
    copy = section_copy("figures")
    share = page.one("div", class_="figure", data_figure="age_65_share")
    assert copy["count_unavailable"] in share.text
    assert copy["count_unavailable"] not in page.one("div", data_figure="population").text
    # Only the three shares are numbers here: no count, published or computed, is shown.
    values = [float(d.attrs["value"]) for d in share.find_all("data", class_="value")]
    assert values == [21.3, 15.0, 19.8]
    population = fixture_row("population", HOUSE_22)
    percent = fixture_row("age_65_share", HOUSE_22)
    assert population is not None and population.value is not None
    assert percent is not None and percent.value is not None
    computed = population.value * percent.value / 100
    for text in (f"{computed:,.0f}", f"{computed:.0f}", f"{round(computed)}"):
        assert text not in page.text
    for data in page.find_all("data"):
        if data.attrs.get("value"):
            assert round(float(data.attrs["value"])) != round(computed)


def test_companion_count_only_from_a_published_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the ETL acquires the published 65+ count, it shows beside the share, cited."""
    section = import_module("app.sections.20_figures")
    kinds = KINDS | {"age_65_share": Kind(kind="share", compared=True, companion_count="X_1E")}
    monkeypatch.setattr(section, "KINDS", kinds)
    published = row("population", HOUSE_22, 4321.0, 210.0).model_copy(update={"variable": "X_1E"})
    for rows, shown in ((ALL_ROWS, False), ([*ALL_ROWS, published], True)):
        path = tmp_path / f"{shown}.db"
        build_db(path, rows)
        monkeypatch.setenv("KYD_FACTS_DB", str(path))
        share = brief(TestClient(app), "/brief/house/22").one("div", data_figure="age_65_share")
        unavailable = section_copy("figures")["count_unavailable"]
        assert (unavailable in share.text) is not shown
        companions = share.find_all(class_="companion-count")
        assert len(companions) == int(shown)
        if shown:
            value = companions[0].one("data", class_="value")
            assert float(value.attrs["value"]) == 4321.0
            assert len(share.find_all("dl", class_="citation")) == 4
        # The sentence itself is unchanged: three readings, one per geography.
        assert len(sentence(share).find_all("span", class_="reading")) == 3


def clauses(node: Node) -> str:
    return sentence(node).text.lower()


def test_indeterminate_caution_and_missing_make_no_claim_and_real_differences_are_worded(
    client: TestClient,
) -> None:
    house = brief(client, "/brief/house/22")
    share = clauses(house.one("div", data_figure="age_65_share"))
    # 21.3 ± 2.1 vs Honolulu 15.0 ± 0.3 is a real difference; vs the state 19.8 ± 0.1 is not.
    assert "a larger share than honolulu county" in share
    assert "about the same share as state of hawaiʻi" in share
    assert "within the margins of error" in share
    assert share.count("larger") == 1 and "smaller" not in share
    # 98,765 ± 30,000 is indeterminate against both references.
    median = clauses(house.one("div", data_figure="median_household_income"))
    assert median.count("about the same as") == 2
    assert not CLAIMS.search(median), median
    senate = brief(client, "/brief/senate/5")
    caution = clauses(senate.one("div", data_figure="age_65_share"))  # 17.5 ± 10: caution
    assert caution.count("no comparison claim") == 2
    assert not CLAIMS.search(caution), caution
    missing = clauses(senate.one("div", data_figure="median_household_income"))
    assert missing.count("no comparison claim") == 2
    assert not CLAIMS.search(missing), missing


GEOS = ("senate:15:007:2022", "county:15:009", "county:15:003", "state:15")
VALUES = (10, 30, 50, 90)
MOES = (2, None, 0, 10)


def test_split_county_fixture_shows_both_counties_with_citations_and_no_strip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "intervals.db"
    build_db(db, [row("population", g, v, m) for g, v, m in zip(GEOS, VALUES, MOES, strict=True)])
    monkeypatch.setenv("KYD_FACTS_DB", str(db))
    mapping = load_mapping()
    first = mapping[GEOS[0]][0]
    mapping[GEOS[0]] = [
        first.model_copy(update={"area_share": 0.5}),
        first.model_copy(update={"county": GEOS[2], "area_share": 0.5}),
    ]
    monkeypatch.setattr(import_module("app.sections.20_figures"), "load_mapping", lambda: mapping)
    response = TestClient(app).get("/brief/senate/7")
    assert response.status_code == 200
    assert "interval-strip" not in response.text
    page = parse(response.text)
    assert page.one("section", class_="figures").find_all("svg") == []
    population = sentence(page.one("div", class_="figure", data_figure="population"))
    for geography, value, moe in zip(GEOS, VALUES, MOES, strict=True):
        reading = population.one("span", class_="reading", data_geography=geography)
        assert float(reading.one("data", class_="value").attrs["value"]) == value
        moe_data = reading.one("span", class_="moe").one("data")
        if moe is None:
            assert moe_data.attrs["value"] == ""
            assert "no margin of error published" in moe_data.text
        else:
            assert float(moe_data.attrs["value"]) == moe
            assert "±" in moe_data.text
    assert "Maui County" in population.text and "Honolulu County" in population.text
    assert "no margin of error published" in page.text
    assert len(page.find_all("dl", class_="citation")) == 4


@pytest.mark.parametrize("split", [False, True])
def test_county_values_moes_and_citations_in_each_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, split: bool
) -> None:
    mapping_path = tmp_path / "counties.tsv"
    with (ROOT / "data/district_counties.tsv").open() as stream:
        records = list(csv.DictReader(stream, delimiter="\t"))
    if split:
        original = next(r for r in records if r["district"] == HOUSE_22)
        original["area_share"] = "0.75"
        records.append(original | {"county": MAUI, "area_share": "0.25"})
    with mapping_path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(records)
    monkeypatch.setattr(counties, "MAPPING_PATH", mapping_path)
    geographies = [HOUSE_22, STATE, HONOLULU]
    if split:
        geographies.append(MAUI)
    facts = [
        row(f, g, 1234 + i * 100, 12 + i) for f in VARIABLES for i, g in enumerate(geographies)
    ]
    db = tmp_path / "facts.db"
    build_db(db, facts)
    monkeypatch.setenv("KYD_FACTS_DB", str(db))
    page = brief(TestClient(app), "/brief/house/22")
    for node in page.find_all("div", class_="figure"):
        figure = node.attrs["data-figure"]
        text = sentence(node)
        assert len(text.find_all("span", class_="reading")) == len(geographies)
        for geography in geographies:
            fact = fixture_row(figure, geography, facts)
            check_span(text.one("span", class_="reading", data_geography=geography), fact, figure)
            assert fact is not None
            check_citation(node.one("dl", data_geography=geography), fact)
    assert "Honolulu County" in page.text
    if split:
        assert "more than one county" in page.text
        assert "Maui County" in page.text
        assert "75.0%" in page.text and "25.0%" in page.text
        assert "area" in page.text
        # Each county's percentage is labelled as a share of district area, beside it.
        items = [
            " ".join(li.text.split()) for li in page.one("section", class_="figures").find_all("li")
        ]
        for name, share in (("Honolulu County", "75.0%"), ("Maui County", "25.0%")):
            item = next(i for i in items if i.startswith(name))
            assert f"{share} — Share of county-covered district area" in item


def test_house_43_from_committed_facts_reads_as_sentences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KYD_FACTS_DB", raising=False)
    response = TestClient(app).get("/brief/house/43")
    assert response.status_code == 200
    page = parse(response.text)
    figures = page.find_all("div", class_="figure")
    assert len(figures) == 3
    for node in figures:
        district = sentence(node).one("span", class_="reading", data_geography="house:15:043:2022")
        assert (
            len(district.find_all(class_="value")) + len(district.find_all(class_="missing")) == 1
        )
        assert node.find_all("dl", class_="citation")
        assert node.find_all("svg") == []


def test_house_43_paints_one_sentence_per_figure_without_any_strip(
    page: Page, base_url: str
) -> None:
    """The work order's evidence page, as Chromium paints it: sentences with readings, no dots."""
    open_page(page, base_url + "/brief/house/43", 1440)
    figures = page.locator(".figure")
    assert figures.count() == 3
    assert page.locator(".figure svg, svg.interval-strip").count() == 0
    for figure in figures.all():
        text = figure.locator("p.reading[data-figure-sentence]")
        assert text.count() == 1
        assert text.is_visible()
        reading = text.locator('span.reading[data-geography="house:15:043:2022"]')
        # The wo122 server's fixture may lack this district: a reading is a value or "missing".
        assert reading.locator("data.value, .missing").count() == 1
        assert reading.locator(".reliability[data-reliability]").count() == 1
