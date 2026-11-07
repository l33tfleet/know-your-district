"""WO #129: when no figure on a brief has a fact-table row, the figures section says once,
in plain words from `app/copy.yaml`, that the figures haven't been loaded yet and where they
will come from; each missing reading shows one phrase, not the old doubled
"No published figure in the fact table yet. not available"."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

import app.copy
from app.facts import acs_config
from app.main import app as asgi_app
from app.models import Fact
from tests.regressions.test_wo97_brief_page import (
    ROWS,
    SENATE_5,
    STATE,
    VARIABLES,
    Node,
    brief,
    build_db,
)
from tests.regressions.test_wo261_figure_sentences import check_span


def figures_copy() -> dict[str, Any]:
    copy: dict[str, Any] = yaml.safe_load(app.copy.COPY_PATH.read_text(encoding="utf-8"))[
        "sections"
    ]["figures"]
    return copy


def section_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[Fact]) -> Node:
    path = tmp_path / "facts.db"
    build_db(path, rows)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return brief(TestClient(asgi_app), "/brief/senate/5").one("section", class_="figures")


def notices(section: Node) -> list[Node]:
    return section.find_all(class_="figures-not-loaded")


def test_empty_fact_table_shows_one_plain_notice_above_the_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = section_for(tmp_path, monkeypatch, [])
    found = notices(section)
    assert len(found) == 1
    vintage, _ = acs_config()
    wording = str(figures_copy()["not_loaded"])
    assert "fact table" not in wording.lower()
    assert found[0].text == " ".join(wording.format(vintage=vintage).split())
    assert vintage in found[0].text
    assert "American Community Survey" in found[0].text
    # The notice comes before the first card.
    order = [c for c in section.children if c is found[0] or c.attrs.get("class") == "figure"]
    assert order[0] is found[0]
    assert "fact table" not in section.text.lower()


def test_empty_fact_table_cards_show_one_missing_phrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = section_for(tmp_path, monkeypatch, [])
    word = str(figures_copy()["reliability"]["unavailable"])
    figures = section.find_all(class_="figure")
    assert len(figures) == 3
    for figure in figures:
        readings = figure.find_all(class_="reading")
        assert len(readings) >= 2
        for reading in readings:
            labels = reading.find_all(class_="reading-label")
            text = reading.text
            if labels:
                text = text.removeprefix(labels[0].text).strip()
            assert text == word, reading.text


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


def test_one_row_is_enough_to_drop_the_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = section_for(tmp_path, monkeypatch, [ROWS[-1]])
    assert notices(section) == []


def test_card_with_no_row_shows_one_missing_phrase_when_other_cards_have_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partly loaded table: the cards with no row at all still read one phrase per reading,
    never the doubled no_row text followed by 'not available'."""
    present = ROWS[-1]
    section = section_for(tmp_path, monkeypatch, [present])
    copy = figures_copy()
    word = str(copy["reliability"]["unavailable"])
    empty = [
        node
        for node in section.find_all(class_="figure")
        if node.attrs["data-variable"] != present.variable
    ]
    assert len(empty) == 2
    for figure in empty:
        assert figure.find_all("p", class_="reading", data_figure_sentence="") == []
        assert str(copy["no_row"]) not in figure.text
        readings = figure.find_all(class_="reading")
        assert len(readings) >= 2
        for reading in readings:
            labels = reading.find_all(class_="reading-label")
            text = reading.text
            if labels:
                text = text.removeprefix(labels[0].text).strip()
            assert text == word, reading.text
