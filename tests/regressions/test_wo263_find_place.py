"""WO #263: find a district by place name (step 1: curated Oʻahu places).

Pins the work order's decisions: the hand-curated `data/places/oahu_places.tsv` (≥ 50 Oʻahu
places, Mōʻiliʻili → House 22, Kāneʻohe → House 48, every row's House and Senate district
checked by point-in-polygon on the committed district shapes); matching that ignores the
ʻokina, kahakō and case; `/find?q=` results that show the correct spelling, the island and
links to `/brief/{chamber}/{n}`; a helpful empty state with close spellings and the number
picker; a home-page searchbox named "Find a district by place" whose listbox goes straight to
the brief; control characters rejected at the edge; axe clean at every impact level.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.main import app
from app.places import PLACES_PATH, Place, close_spellings, find, fold, load_places
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
HEADER = "place\talias\thouse\tsenate\tlon\tlat"
client = TestClient(app)

Ring = list[list[float]]


# --- point-in-polygon over the committed district shapes ---


def shapes(chamber: str) -> list[tuple[int, list[list[Ring]]]]:
    """(district, polygons) per feature; a polygon is its outer ring then its holes."""
    collection = json.loads((ROOT / f"data/geo/{chamber}.geojson").read_text(encoding="utf-8"))
    out: list[tuple[int, list[list[Ring]]]] = []
    for feature in collection["features"]:
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        out.append((int(feature["properties"]["district"]), polygons))
    return out


def in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def districts_at(chamber: str, lon: float, lat: float) -> list[int]:
    return [
        district
        for district, polygons in SHAPES[chamber]
        if any(
            in_ring(lon, lat, polygon[0]) and not any(in_ring(lon, lat, h) for h in polygon[1:])
            for polygon in polygons
        )
    ]


SHAPES = {"house": shapes("house"), "senate": shapes("senate")}
PLACES = load_places()


def test_point_in_polygon_honours_holes() -> None:
    """The check itself: a point in a hole is outside its polygon."""
    square: Ring = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    hole: Ring = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
    SHAPES["test"] = [(1, [[square, hole]]), (2, [[hole]])]
    try:
        assert districts_at("test", 0.5, 0.5) == [1]
        assert districts_at("test", 2, 2) == [2]
        assert districts_at("test", 5, 5) == []
    finally:
        del SHAPES["test"]


# --- the curated file ---


def test_file_has_the_decided_header_and_at_least_50_places() -> None:
    lines = PLACES_PATH.read_text(encoding="utf-8").splitlines()
    assert PLACES_PATH == ROOT / "data/places/oahu_places.tsv"
    assert lines[0] == HEADER
    assert len(lines) - 1 == len(PLACES) >= 50
    assert {p.island for p in PLACES} == {"Oʻahu"}


def test_anchor_places() -> None:
    by_name = {p.place: p for p in PLACES}
    assert by_name["Mōʻiliʻili"].house == 22
    assert by_name["Kāneʻohe"].house == 48
    assert by_name["Waimea"].house == 47


@pytest.mark.parametrize("place", PLACES, ids=lambda p: p.alias)
def test_every_row_lies_in_its_house_and_senate_district(place: Place) -> None:
    assert districts_at("house", place.lon, place.lat) == [place.house]
    assert districts_at("senate", place.lon, place.lat) == [place.senate]


def test_spelling_in_the_file() -> None:
    for p in PLACES:
        assert p.alias.isascii(), p.alias
        assert fold(p.alias) == fold(p.place), p.place
        assert not re.search("['\u2018\u2019`\u00b4]", p.place), p.place
        assert unicodedata.normalize("NFC", p.place) == p.place, p.place
    names = {p.place for p in PLACES}
    for name in ("Kāneʻohe", "Mōʻiliʻili", "Waiʻanae", "ʻAiea", "Haleʻiwa", "Lāʻie"):
        assert name in names


# --- the loader's rejections, one check each ---

GOOD = "Kāneʻohe\tKaneohe\t48\t24\t-157.8\t21.42\n"


def write(tmp_path: Path, body: str, header: str = HEADER) -> Path:
    path = tmp_path / "places.tsv"
    path.write_text(header + "\n" + body, encoding="utf-8")
    return path


def test_loader_reads_a_good_file(tmp_path: Path) -> None:
    (place,) = load_places(write(tmp_path, GOOD))
    assert (place.place, place.alias, place.house, place.senate) == ("Kāneʻohe", "Kaneohe", 48, 24)


def test_loader_rejects_a_wrong_header(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="header"):
        load_places(write(tmp_path, GOOD, header="place\talias\thouse\tlon\tlat"))


def test_loader_rejects_a_short_row(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="6 fields"):
        load_places(write(tmp_path, "Kāneʻohe\tKaneohe\t48\t24\t-157.8\n"))


def test_loader_rejects_names_that_fold_alike(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fold"):
        load_places(write(tmp_path, GOOD + "Kaneʻohe\tKaneohe\t49\t24\t-157.8\t21.41\n"))


def test_loader_rejects_a_house_district_out_of_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="house"):
        load_places(write(tmp_path, "Kāneʻohe\tKaneohe\t52\t24\t-157.8\t21.42\n"))


def test_loader_rejects_a_senate_district_out_of_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="senate"):
        load_places(write(tmp_path, "Kāneʻohe\tKaneohe\t48\t26\t-157.8\t21.42\n"))


def test_loader_rejects_a_non_ascii_alias(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ASCII"):
        load_places(write(tmp_path, "Kāneʻohe\tKāneohe\t48\t24\t-157.8\t21.42\n"))


def test_loader_rejects_an_alias_of_another_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="alias"):
        load_places(write(tmp_path, "Kāneʻohe\tKailua\t48\t24\t-157.8\t21.42\n"))


@pytest.mark.parametrize("wrong", ["'", "\u2018", "\u2019", "`"])
def test_loader_rejects_an_okina_lookalike_in_the_place(tmp_path: Path, wrong: str) -> None:
    with pytest.raises(ValueError, match="U\\+02BB"):
        load_places(write(tmp_path, f"Kāne{wrong}ohe\tKaneohe\t48\t24\t-157.8\t21.42\n"))


# --- matching ---

KANEOHE_SPELLINGS = (
    "Kaneohe",
    "kāneʻohe",
    "Kaneʻohe",
    "Kane'ohe",
    "KANE\u2018OHE",
    "Kane\u2019ohe",
    "  kaneohe ",
    "Ka\u0304ne\u02bbohe",  # decomposed kahakō
)


@pytest.mark.parametrize("q", KANEOHE_SPELLINGS)
def test_matching_ignores_okina_kahako_and_case(q: str) -> None:
    assert [p.place for p in find(q)] == ["Kāneʻohe"]


def test_fold_collapses_whitespace() -> None:
    assert fold("  Pearl \t  City ") == "pearl city"


def test_several_places_share_a_word() -> None:
    assert [p.place for p in find("valley")] == ["Kalama Valley", "Kalihi Valley", "Niu Valley"]


def test_exact_name_wins_over_longer_names() -> None:
    assert [p.place for p in find("Kalihi")] == ["Kalihi"]


def test_short_queries_match_only_exactly() -> None:
    assert find("ka") == []
    assert find("") == []


def test_close_spellings_for_a_typo() -> None:
    assert "Kāneʻohe" in [p.place for p in close_spellings("Kanehoe")]


# --- routes ---


def links(html: str) -> list[str]:
    return re.findall(r'href="(/brief/[^"]*)"', html)


@pytest.mark.parametrize("q", KANEOHE_SPELLINGS)
def test_find_kaneohe_shows_place_island_and_both_briefs(q: str) -> None:
    response = client.get("/find", params={"q": q})
    assert response.status_code == 200
    html = response.text
    assert "Kāneʻohe" in html
    assert "Oʻahu" in html
    assert links(html) == ["/brief/house/48", "/brief/senate/24"]


def test_find_waimea_shows_its_island() -> None:
    html = client.get("/find", params={"q": "Waimea"}).text
    assert re.search(r"Waimea</[a-z]+>,\s*Oʻahu", html), html
    assert links(html) == ["/brief/house/47", "/brief/senate/23"]


def test_find_several_lists_each() -> None:
    html = client.get("/find", params={"q": "valley"}).text
    assert html.count('class="find-result"') == 3
    assert links(html) == [
        "/brief/house/18",
        "/brief/senate/25",
        "/brief/house/29",
        "/brief/senate/14",
        "/brief/house/19",
        "/brief/senate/9",
    ]


def test_every_result_link_opens_a_brief() -> None:
    html = client.get("/find", params={"q": "Kaneohe"}).text
    for href in links(html):
        assert re.fullmatch(r"/brief/(house|senate)/\d+", href)
        assert client.get(href).status_code == 200


def test_unknown_place_says_so_suggests_and_keeps_the_picker() -> None:
    response = client.get("/find", params={"q": "Kanehoe"})
    assert response.status_code == 200
    html = response.text
    assert "No Oʻahu place matches" in html
    assert "Kanehoe" in html
    assert 'href="/find?q=K%C4%81ne%CA%BBohe"' in html
    assert 'class="picker" action="/brief"' in html
    assert links(html) == []


def test_unknown_place_without_close_spellings_still_offers_the_picker() -> None:
    html = client.get("/find", params={"q": "zzzzzz"}).text
    assert "No Oʻahu place matches" in html
    assert "Close spellings" not in html
    assert 'class="picker" action="/brief"' in html


def test_empty_query_prompts() -> None:
    html = client.get("/find").text
    assert "Type the name of a place on Oʻahu" in html
    assert 'role="search"' in html


@pytest.mark.parametrize("path", ["/find", "/find/options"])
@pytest.mark.parametrize("bad", ["Kane\x00ohe", "Kane\nohe", "Kane\x7fohe"])
def test_control_characters_are_rejected(path: str, bad: str) -> None:
    response = client.get(path, params={"q": bad})
    assert response.status_code == 400
    assert "control characters" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/find", "/find/options"])
def test_overlong_query_is_rejected(path: str) -> None:
    response = client.get(path, params={"q": "a" * 101})
    assert response.status_code == 400
    assert "100 characters" in response.json()["detail"]


def test_options_go_straight_to_the_brief() -> None:
    html = client.get("/find/options", params={"q": "Moiliili"}).text
    assert re.search(r'<a role="option" href="/brief/house/22"[^>]*aria-label="Mōʻiliʻili"', html)


def test_options_are_capped() -> None:
    html = client.get("/find/options", params={"q": "wai"}).text
    assert html.count('role="option"') == 8


def test_home_has_the_searchbox_beside_the_picker() -> None:
    html = client.get("/").text
    assert re.search(r'<form class="place-search" role="search" action="/find" method="get"', html)
    assert '<label for="place">Find a district by place</label>' in html
    assert re.search(r'<input type="search" id="place" name="q"', html)
    assert 'role="listbox"' in html
    assert 'class="picker" action="/brief"' in html


# --- in a browser ---

PAGES = ("/", "/find?q=Kaneohe", "/find?q=valley", "/find?q=Kanehoe", "/find")


def all_axe_violations(page: Page) -> list[str]:
    """axe-core violations at every impact level, minor included."""
    page.evaluate(AXE_JS)
    violations = cast(
        list[dict[str, object]],
        page.evaluate(
            "async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
            ".map(v => ({id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target)}))"
        ),
    )
    return [f"{v['id']} ({v['impact']}): {v['targets']}" for v in violations]


@pytest.mark.parametrize("width", (390, 1440))
@pytest.mark.parametrize("path", PAGES)
def test_pages_axe_clean_and_spelled(page: Page, base_url: str, path: str, width: int) -> None:
    open_page(page, base_url + path, width)
    assert all_axe_violations(page) == []
    assert spelling_problems(page_text(page)) == []


@pytest.mark.parametrize("width", (390, 1440))
def test_open_listbox_axe_clean(page: Page, base_url: str, width: int) -> None:
    open_page(page, base_url + "/", width)
    page.get_by_role("searchbox", name="Find a district by place").fill("wai")
    page.get_by_role("listbox").get_by_role("option").first.wait_for()
    assert all_axe_violations(page) == []


def test_story_step_1(page: Page, base_url: str) -> None:
    """As the story runner plays it: fill, count the listbox at once, pick the option."""
    open_page(page, base_url + "/", 1440)
    page.get_by_role("searchbox", name="Find a district by place").fill("Mōʻiliʻili")
    assert page.get_by_role("listbox").count() == 1
    page.get_by_role("listbox").get_by_role("option", name="Mōʻiliʻili", exact=True).click()
    page.get_by_role("heading", name="Hawaiʻi State House District 22").wait_for(timeout=8000)
    assert page.url == base_url + "/brief/house/22"


def test_keyboard_only_through_the_listbox(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    searchbox = page.get_by_role("searchbox", name="Find a district by place")
    for _ in range(40):
        page.keyboard.press("Tab")
        if searchbox.evaluate("e => e === document.activeElement"):
            break
    else:
        pytest.fail("the searchbox is not reachable by Tab")
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


def test_keyboard_submit_without_the_listbox(page: Page, base_url: str) -> None:
    """Enter in the searchbox submits the plain form to /find."""
    open_page(page, base_url + "/", 1440)
    page.get_by_role("searchbox", name="Find a district by place").fill("Kaneohe")
    page.keyboard.press("Enter")
    page.wait_for_url(base_url + "/find?q=Kaneohe")
    assert page.get_by_role("link", name="House District 48").count() == 1
    assert page.get_by_role("link", name="Senate District 24").count() == 1
