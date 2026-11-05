"""WO201: every brief uses its qualified boundary identity and complete island membership."""

import re
from functools import cache
from html import escape

import pytest
from fastapi.testclient import TestClient

import app.copy
from app.boundary_store import load_boundaries
from app.copy import geography_name
from app.main import app as asgi_app
from app.svg import render_svg

STORE = load_boundaries()


@pytest.fixture(autouse=True)
def stable_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wording stays fixed during each request; avoid repeatedly parsing the same YAML
    # in unrelated brief sections while checking all 76 geometry integrations.
    monkeypatch.setattr(app.copy, "load_copy", cache(app.copy.load_copy))


@pytest.mark.parametrize("key", sorted(STORE.districts))
def test_every_brief_displays_its_boundary_and_sources(key: str) -> None:
    boundary = STORE.district(key)
    response = TestClient(asgi_app).get(
        f"/brief/{boundary.district.chamber}/{boundary.district.district}"
    )
    assert response.status_code == 200
    header = re.search(r'<header class="brief-headline">(.*?)</header>', response.text, re.S)
    assert header is not None
    expected = render_svg(
        boundary.geometry,
        geography_name(key),
        [(i.name, i.geometry) for i in boundary.islands],
    )
    assert expected in header[1]
    assert escape(boundary.attribution.credit.replace("Hawaii", "Hawaiʻi")) in header[1]
    assert "2020–2024" in header[1] and "2022 plan" in header[1]
    for island in boundary.islands:
        assert escape(island.name, quote=True) in header[1]
        if island.coastline.status == "available":
            assert escape(island.coastline.source.credit) in header[1]
