"""WO201: every brief uses its stored boundary and the sole SVG renderer."""

import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app.boundary_store import load_boundaries
from app.copy import geography_name
from app.main import app
from app.svg import render_svg

STORE = load_boundaries()


@pytest.mark.parametrize("district_id", sorted(STORE.districts))
def test_all_briefs_show_their_stored_outline_and_state_source(district_id: str) -> None:
    boundary = STORE.district(district_id)
    district = boundary.district
    response = TestClient(app).get(f"/brief/{district.chamber}/{int(district.district)}")
    assert response.status_code == 200
    headline = re.search(r'<header class="brief-headline">(.*?)</header>', response.text, re.S)
    assert headline is not None
    expected = render_svg(
        boundary.geometry,
        geography_name(district_id),
        tuple((island.name, island.geometry) for island in boundary.islands),
    )
    assert expected in headline[1]
    assert str(boundary.attribution.provenance.source_url) in unescape(headline[1])
    assert "State of Hawaiʻi Office of Elections" in unescape(headline[1])
    assert boundary.attribution.provenance.method in unescape(headline[1])
    assert str(boundary.attribution.provenance.retrieved_on) in headline[1]
