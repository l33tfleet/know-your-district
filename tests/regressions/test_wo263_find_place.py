"""WO #263: find a district by place name (step 1: curated Oʻahu places, House only).

Pins the §16 decision: a hand-curated `data/places/oahu_places.tsv` (header place, alias,
house, lon, lat; ≥ 50 Oʻahu places incl. Mōʻiliʻili → 22, Kāneʻohe → 48), each row's House
district checked by point-in-polygon on `data/geo/house.geojson`; matching that ignores the
ʻokina, kahakō and case; one match goes straight to the brief (303), several are listed, none
says so and keeps the number picker; a home-page searchbox named "Find a district by place".
"""

import json
import re
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.main import app
from app.places import PLACES_PATH, Place, find, fold, load_places
from tests.regressions.test_wo122_browser_checks import (
    AXE_JS,
    base_url,
    browser,
    open_page,
    page,
    page_text,
    spelling_problems,
)

# Reuse the WO122 server and Chromium fixtures without modifying their source.
__all__ = ["base_url", "browser", "page"]

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app, follow_redirects=False)
Ring = list[list[float]]


def in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def house_districts_at(lon: float, lat: float) -> list[int]:
    found: list[int] = []
    for feature in HOUSE["features"]:
        geometry = feature["geometry"]
        coords = geometry["coordinates"]
        polygons = coords if geometry["type"] == "MultiPolygon" else [coords]
        if any(
            in_ring(lon, lat, p[0]) and not any(in_ring(lon, lat, h) for h in p[1:])
            for p in polygons
        ):
            found.append(int(feature["properties"]["district"]))
    return found


HOUSE = json.loads((ROOT / "data/geo/house.geojson").read_text(encoding="utf-8"))
PLACES = load_places()


def test_file_has_the_decided_header_and_at_least_50_places() -> None:
    lines = PLACES_PATH.read_text(encoding="utf-8").splitlines()
    assert PLACES_PATH == ROOT / "data/places/oahu_places.tsv"
    assert lines[0] == "place\talias\thouse\tlon\tlat"
    assert len(lines) - 1 == len(PLACES) >= 50
    by_name = {p.place: p.house for p in PLACES}
    assert by_name["Mōʻiliʻili"] == 22
    assert by_name["Kāneʻohe"] == 48


@pytest.mark.parametrize("place", PLACES, ids=lambda p: p.alias)
def test_every_row_lies_in_its_house_district(place: Place) -> None:
    assert house_districts_at(place.lon, place.lat) == [place.house]


def test_spelling_in_the_file() -> None:
    for p in PLACES:
        assert p.alias.isascii() and fold(p.alias) == fold(p.place), p.place
        assert not any(chr(c) in p.place for c in (0x27, 0x2018, 0x2019, 0x60)), p.place


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "places.tsv"
    path.write_text("place\talias\thouse\tlon\tlat\n" + body, encoding="utf-8")
    return path


ROW = "Kāneʻohe\tKaneohe\t48\t-157.8\t21.42\n"


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (ROW + ROW, "duplicate"),
        ("Kāneʻohe\tKaneohe\t52\t-157.8\t21.42\n", "house"),
        ("Kāneʻohe\tKaneohe\t48\t24\t-157.8\t21.42\n", "5 fields"),
    ],
)
def test_loader_rejects_bad_rows(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_places(write(tmp_path, body))


KANEOHE = ("Kaneohe", "kāneʻohe", "Kaneʻohe", "KANE'OHE", "Kāneʻohe")


@pytest.mark.parametrize("q", KANEOHE)
def test_matching_ignores_okina_kahako_and_case(q: str) -> None:
    assert [p.place for p in find(q)] == ["Kāneʻohe"]


@pytest.mark.parametrize("q", KANEOHE)
def test_one_match_goes_straight_to_the_house_brief(q: str) -> None:
    response = client.get("/find", params={"q": q})
    assert response.status_code == 303
    assert response.headers["location"] == "/brief/house/48"


def test_moiliili_goes_to_house_22() -> None:
    assert client.get("/find?q=Moiliili").headers["location"] == "/brief/house/22"


def test_several_matches_are_listed_with_spelling_island_and_links() -> None:
    response = client.get("/find", params={"q": "valley"})
    assert response.status_code == 200
    html = response.text
    assert re.findall(r'href="(/brief/[^"]*)"', html) == [
        "/brief/house/18",
        "/brief/house/29",
        "/brief/house/19",
    ]
    for name in ("Kalama Valley", "Kalihi Valley", "Niu Valley"):
        assert name in html
    assert html.count("Oʻahu") >= 3
    assert "/brief/senate/" not in html
    for href in re.findall(r'href="(/brief/[^"]*)"', html):
        assert client.get(href).status_code == 200


def test_no_match_says_so_suggests_and_keeps_the_picker() -> None:
    response = client.get("/find", params={"q": "Kanehoe"})
    assert response.status_code == 200
    html = response.text
    assert "No Oʻahu place matches" in html
    assert 'href="/find?q=K%C4%81ne%CA%BBohe"' in html
    assert 'class="picker" action="/brief"' in html
    assert "/brief/house/" not in html


def test_home_has_the_searchbox_beside_the_picker() -> None:
    html = client.get("/").text
    assert '<form class="place-search" role="search" action="/find" method="get">' in html
    assert '<label for="q">Find a district by place</label>' in html
    assert re.search(r'<input type="search" id="q" name="q"', html)
    assert 'class="picker" action="/brief"' in html


def axe_violations(page: Page) -> list[str]:
    page.evaluate(AXE_JS)
    violations = cast(
        list[dict[str, object]],
        page.evaluate(
            "async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
            ".map(v => ({id: v.id, targets: v.nodes.map(n => n.target)}))"
        ),
    )
    return [f"{v['id']}: {v['targets']}" for v in violations]


@pytest.mark.parametrize("path", ["/", "/find?q=valley", "/find?q=Kanehoe", "/find"])
def test_pages_axe_clean_and_spelled(page: Page, base_url: str, path: str) -> None:
    open_page(page, base_url + path, 390)
    assert axe_violations(page) == []
    assert spelling_problems(page_text(page)) == []


def test_keyboard_search_opens_the_brief(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    searchbox = page.get_by_role("searchbox", name="Find a district by place")
    for _ in range(40):
        page.keyboard.press("Tab")
        if searchbox.evaluate("e => e === document.activeElement"):
            break
    else:
        pytest.fail("the searchbox is not reachable by Tab")
    page.keyboard.type("Kaneohe")
    page.keyboard.press("Enter")
    page.wait_for_url(base_url + "/brief/house/48")


# --- story step 1: the as-you-type listbox (.factory/story.journey) ---


def test_options_go_straight_to_the_brief() -> None:
    html = client.get("/find/options", params={"q": "Moiliili"}).text
    assert re.search(r'<a role="option" href="/brief/house/22"[^>]*aria-label="Mōʻiliʻili"', html)
    assert "/brief/senate/" not in html


def test_options_are_capped_and_empty_for_no_match() -> None:
    assert client.get("/find/options", params={"q": "wai"}).text.count('role="option"') == 8
    assert 'role="option"' not in client.get("/find/options", params={"q": "zzzz"}).text


def test_home_searchbox_controls_an_always_present_listbox() -> None:
    html = client.get("/").text
    assert re.search(
        r'<input type="search" id="q" name="q"[^>]*aria-controls="place-options"', html
    )
    assert re.search(
        r'id="place-options"[^>]*role="listbox"[^>]*aria-label="Matching places"', html
    )


def test_story_step_1(page: Page, base_url: str) -> None:
    """As the story runner plays it: fill, find the one listbox at once, pick the option."""
    open_page(page, base_url + "/", 1440)
    page.get_by_role("searchbox", name="Find a district by place").fill("Mōʻiliʻili")
    assert page.get_by_role("listbox").count() == 1
    page.get_by_role("listbox").get_by_role("option", name="Mōʻiliʻili", exact=True).click()
    page.get_by_role("heading", name="Hawaiʻi State House District 22").wait_for(timeout=8000)
    assert page.url == base_url + "/brief/house/22"


def test_open_listbox_axe_clean(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 390)
    page.get_by_role("searchbox", name="Find a district by place").fill("valley")
    page.get_by_role("listbox").get_by_role("option").first.wait_for()
    assert axe_violations(page) == []


def test_keyboard_only_through_the_listbox(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    page.get_by_role("searchbox", name="Find a district by place").focus()
    page.keyboard.type("Moiliili")
    option = page.get_by_role("option", name="Mōʻiliʻili", exact=True)
    option.wait_for()
    for _ in range(3):  # past the submit button to the first option
        page.keyboard.press("Tab")
        if option.evaluate("e => e === document.activeElement"):
            break
    else:
        pytest.fail("the option is not reachable by Tab from the searchbox")
    page.keyboard.press("Enter")
    page.wait_for_url(base_url + "/brief/house/22")


@pytest.mark.parametrize(
    "text",
    [
        "",
        ROW,
        "place\talias\thouse\tlon\n" + ROW,
        "Place\tAlias\tHouse\tLon\tLat\n" + ROW,
        "alias\tplace\thouse\tlon\tlat\n" + ROW,
    ],
    ids=["empty", "no-header", "missing-column", "wrong-case", "wrong-order"],
)
def test_loader_rejects_a_missing_or_wrong_header(tmp_path: Path, text: str) -> None:
    path = tmp_path / "places.tsv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="header must be"):
        load_places(path)


CONTROL_QUERIES = [
    "Kaneohe\x00",
    "\x1fKaneohe",
    "Kane\nohe",
    "Kaneohe\t",
    "\x07",
    " \r",
    "Kaneohe\x7f",
]


@pytest.mark.parametrize("path", ["/find", "/find/options"])
@pytest.mark.parametrize("q", CONTROL_QUERIES)
def test_search_rejects_control_characters(path: str, q: str) -> None:
    response = client.get(path, params={"q": q})
    assert response.status_code == 400
    assert "location" not in response.headers
    assert 'role="option"' not in response.text


@pytest.mark.parametrize("path", ["/find", "/find/options"])
def test_search_still_accepts_plain_spaces(path: str) -> None:
    assert client.get(path, params={"q": "  Kaneohe  "}).status_code in (200, 303)
