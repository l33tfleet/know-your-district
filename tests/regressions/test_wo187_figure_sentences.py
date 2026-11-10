"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.counties as counties
from app.analysis.reliability import FLAG_WORDS
from app.copy import section_copy
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
from tests.regressions.test_wo122_browser_checks import base_url, browser, page
from tests.regressions.test_wo129_figures_not_loaded import notices, section_for
from tests.regressions.test_wo261_figure_sentences import (
    COUNTY,
    HONOLULU,
    MAUI,
    MOE_TEXT,
    ROOT,
    VALUE_TEXT,
    client,
    fixture_row,
    sentence,
)

__all__ = [
    "COUNTY",
    "HONOLULU",
    "HOUSE_22",
    "MAUI",
    "MOE_TEXT",
    "ROOT",
    "ROWS",
    "SENATE_5",
    "STATE",
    "VALUE_TEXT",
    "VARIABLES",
    "Node",
    "base_url",
    "brief",
    "browser",
    "build_db",
    "check_citation",
    "client",
    "fixture_row",
    "notices",
    "page",
    "row",
    "section_for",
    "sentence",
]

NA = "This figure is not available"


# Copy of test_wo261_figure_sentences.py::check_span, with the #187 wording.
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
        assert value.attrs["value"] == "" and value.text == NA
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


# Replaces test_wo261_figure_sentences.py::test_each_figure_is_one_sentence_whose_values_and_citations_equal_the_rows (wording only, #187).
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


# Replaces test_wo261_figure_sentences.py::test_county_values_moes_and_citations_in_each_sentence (wording only, #187).
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
        # Each county's percentage is labelled, beside it, as a share of the district's
        # county-covered area (the denominator etl/boundaries/counties.py uses).
        items = [
            " ".join(li.text.split()) for li in page.one("section", class_="figures").find_all("li")
        ]
        for name, share in (("Honolulu County", "75.0%"), ("Maui County", "25.0%")):
            item = next(i for i in items if i.startswith(name))
            assert f"{share} — Share of the district's area covered by counties" in item


def test_county_share_label_keeps_the_county_covered_denominator() -> None:
    """The label names the denominator the ETL divides by, never the whole district.

    Two counties each covering a quarter of a district show 50% each, because
    _shares divides by the sum of county overlaps; a label calling that a share of
    the district's area would misstate it.
    """
    from etl.boundaries.counties import _shares  # pyright: ignore[reportPrivateUsage]
    from etl.boundaries.overlay import Geometry

    def box(x0: float, x1: float) -> Geometry:
        return [[[(x0, 0.0), (x1, 0.0), (x1, 1.0), (x0, 1.0), (x0, 0.0)]]]

    shares = _shares(box(0, 4), {"a": box(0, 1), "b": box(3, 4)})
    assert shares == {"a": 0.5, "b": 0.5}  # each covers only a quarter of the district
    label = section_copy("figures")["county_area"]
    assert label == "Share of the district's area covered by counties"
    # Never the whole district: the old label ended "area in this county".
    assert label.endswith("covered by counties") and "in this county" not in label


# Replaces test_wo129_figures_not_loaded.py::test_rows_present_show_no_notice_and_cards_as_before (wording only, #187).
def test_rows_present_show_no_notice_and_cards_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = section_for(tmp_path, monkeypatch, list(ROWS))
    assert notices(section) == []
    for node in section.find_all(class_="figure"):
        figure = node.attrs["data-figure"]
        variable = VARIABLES[figure][0]
        for geography in (SENATE_5, STATE):
            fact = next(r for r in ROWS if r.variable == variable and r.geography == geography)
            sentence = node.one("p", class_="reading", data_figure_sentence="")
            check_span(
                sentence.one("span", class_="reading", data_geography=geography), fact, figure
            )
