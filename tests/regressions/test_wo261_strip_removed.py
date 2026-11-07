"""WO261 step 2 (#283): the unlabeled dot-and-whisker strip is gone; readings stay.

Replaces `test_wo144_intervals.py::test_rendered_strips_preserve_all_counties_and_published_
intervals` for the new spec: no `svg.interval-strip`, and every geography the strip used to
draw (district, both counties, state) still has its reading, ±MOE and citation (rules 1–2).
"""

# The imports marked unused below served only the two-county test that #284 superseded; the
# AST-level append-only rule allows deleting that test but no other code change here.
from importlib import import_module  # noqa: F401  # pyright: ignore[reportUnusedImport]
from pathlib import Path  # noqa: F401  # pyright: ignore[reportUnusedImport]

import pytest
from fastapi.testclient import TestClient

from app.counties import load_mapping  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.main import app
from tests.regressions.test_wo97_brief_page import (
    build_db,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    parse,
    row,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)

GEOS = ("senate:15:007:2022", "county:15:009", "county:15:003", "state:15")
VALUES = (10, 30, 50, 90)
MOES = (2, None, 0, 10)


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
