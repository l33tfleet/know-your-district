"""WO144: one shared linear scale, with only published intervals drawn."""

from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.intervals import interval_layout
from app.counties import load_mapping
from app.main import app
from tests.regressions.test_wo97_brief_page import build_db, parse, row

GEOS = ("senate:15:007:2022", "county:15:009", "county:15:003", "state:15")


def test_proportional_offsets_and_widths() -> None:
    marks = interval_layout(
        [
            row("population", g, v, m)
            for g, v, m in zip(GEOS, (10, 30, 50, 90), (20, 10, 0, 10), strict=True)
        ]
    )
    a, b, c, d = marks
    assert [m.geography for m in marks] == list(GEOS)
    assert a.low == pytest.approx(0)  # negative endpoint is retained
    assert d.high == pytest.approx(100)
    assert (c.dot - a.dot) / (b.dot - a.dot) == pytest.approx(2)
    assert a.low is not None and a.high is not None
    assert b.low is not None and b.high is not None
    assert (a.high - a.low) / (b.high - b.low) == pytest.approx(2)
    assert c.low == c.dot == c.high  # published zero MOE is an interval


def test_missing_values_and_moes() -> None:
    marks = interval_layout(
        [None, row("population", GEOS[0], None, 500), row("population", GEOS[-1], 20, None)]
    )
    assert len(marks) == 1
    assert marks[0].dot == 100  # zero belongs to the domain even without an interval
    assert marks[0].low is None and marks[0].high is None
    assert interval_layout([None, row("population", GEOS[0], None, None)]) == []


def test_all_zero_values_have_finite_coordinates() -> None:
    marks = interval_layout(
        [row("population", g, 0, m) for g, m in zip(GEOS, (0, None, 0, None), strict=True)]
    )
    assert all(m.dot == 0 for m in marks)
    assert marks[0].low == marks[0].high == 0
    assert marks[1].low is None


def test_rendered_strips_preserve_all_counties_and_published_intervals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "intervals.db"
    build_db(
        db,
        [
            row("population", g, v, m)
            for g, v, m in zip(GEOS, (10, 30, 50, 90), (2, None, 0, 10), strict=True)
        ],
    )
    monkeypatch.setenv("KYD_FACTS_DB", str(db))
    mapping = load_mapping()
    first = mapping[GEOS[0]][0]
    mapping[GEOS[0]] = [
        first.model_copy(update={"area_share": 0.5}),
        first.model_copy(update={"county": GEOS[2], "area_share": 0.5}),
    ]
    monkeypatch.setattr(import_module("app.sections.20_figures"), "load_mapping", lambda: mapping)
    page = parse(TestClient(app).get("/brief/senate/7").text)
    strips = page.find_all("svg", class_="interval-strip")
    assert len(strips) == 1  # the two entirely missing figures have no strip
    strip = strips[0]
    assert strip.attrs["aria-hidden"] == "true" and strip.attrs["focusable"] == "false"
    assert "tabindex" not in strip.attrs
    groups = strip.find_all("g")
    assert [g.attrs["data-geography"] for g in groups] == list(GEOS)
    assert [g.attrs["data-role"] for g in groups] == ["district", "county", "county", "state"]
    assert [len(g.find_all("circle")) for g in groups] == [1, 1, 1, 1]
    assert [len(g.find_all("line")) for g in groups] == [1, 0, 1, 1]
    dots = [float(g.one("circle").attrs["cx"]) for g in groups]
    assert (dots[2] - dots[0]) / (dots[1] - dots[0]) == pytest.approx(2)
    assert "no margin of error published" in page.text
    assert len(page.find_all("dl", class_="citation")) == 4
