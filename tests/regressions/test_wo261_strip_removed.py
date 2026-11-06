"""WO261 step 2 (#283): the unlabeled dot-and-whisker strip is gone; readings stay.

Replaces `test_wo144_intervals.py::test_rendered_strips_preserve_all_counties_and_published_
intervals` for the new spec: no `svg.interval-strip`, and every geography the strip used to
draw (district, both counties, state) still has its reading, ±MOE and citation (rules 1–2).
"""

from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.counties import load_mapping
from app.main import app
from tests.regressions.test_wo97_brief_page import build_db, parse, row

GEOS = ("senate:15:007:2022", "county:15:009", "county:15:003", "state:15")
VALUES = (10, 30, 50, 90)
MOES = (2, None, 0, 10)


def test_two_county_fixture_has_readings_and_citations_but_no_strip(
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
    assert page.find_all("svg", class_="interval-strip") == []
    population = page.one("div", class_="figure", data_figure="population")
    for geography, value, moe in zip(GEOS, VALUES, MOES, strict=True):
        reading = population.one("p", class_="reading", data_geography=geography)
        assert float(reading.one("data", class_="value").attrs["value"]) == value
        moe_data = reading.one("span", class_="moe").one("data")
        if moe is None:
            assert moe_data.attrs["value"] == ""
            assert "no margin of error published" in moe_data.text
        else:
            assert float(moe_data.attrs["value"]) == moe
            assert "±" in moe_data.text
    assert "no margin of error published" in page.text
    assert len(page.find_all("dl", class_="citation")) == 4


def test_house_43_from_committed_facts_shows_figures_without_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KYD_FACTS_DB", raising=False)
    response = TestClient(app).get("/brief/house/43")
    assert response.status_code == 200
    page = parse(response.text)
    figures = page.find_all("div", class_="figure")
    assert len(figures) == 3
    for figure in figures:
        assert figure.find_all("p", class_="reading")
        assert figure.find_all("dl", class_="citation")
    assert page.find_all("svg", class_="interval-strip") == []
    assert "interval-strip" not in response.text
