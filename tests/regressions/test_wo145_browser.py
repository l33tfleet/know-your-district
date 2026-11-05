"""#201: offline complete briefs, multi-island fallbacks, accessibility and print."""

import importlib
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page, Route

from app.boundary_store import IslandBoundary, load_boundaries
from app.main import app
from etl.boundaries import MultiPolygon
from etl.islands import Available, Unavailable
from tests.regressions.test_wo122_browser_checks import axe_problems, browser, page
from tests.regressions.test_wo143_integration import assert_complete_house_22, pdf_pages

__all__ = ["browser", "page"]
ROOT = Path(__file__).resolve().parents[2]
headline = importlib.import_module("app.sections.10_headline")


@pytest.fixture
def offline(page: Page, monkeypatch: pytest.MonkeyPatch) -> Iterator[Page]:
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    client = TestClient(app)

    def serve(route: Route) -> None:
        response = client.get(route.request.url.replace("http://kyd", ""))
        route.fulfill(
            body=response.content,
            status=response.status_code,
            content_type=response.headers.get("content-type", "text/html"),
        )

    page.set_default_navigation_timeout(60_000)
    page.route("**/*", serve)
    assert client.get("/healthz").json() == {"status": "ok"}
    yield page


@pytest.mark.parametrize("district", ["house/22", "senate/8"])
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("variant", ["", "a", "b"])
def test_complete_briefs_accessible_mobile_and_print(
    offline: Page, district: str, width: int, variant: str, tmp_path: Path
) -> None:
    offline.set_viewport_size({"width": width, "height": 900})
    offline.goto(f"http://kyd/brief/{district}" + (f"?v={variant}" if variant else ""))
    image = offline.get_by_role("img").filter(has=offline.locator("path"))
    assert image.count() == 1 and image.is_visible()
    assert axe_problems(offline) == []
    assert offline.evaluate("document.documentElement.scrollWidth <= innerWidth")
    box = image.bounding_box()
    title = offline.locator("h1").bounding_box()
    assert box is not None and title is not None
    assert box["x"] >= title["x"] + title["width"]
    if district == "house/22":
        assert_complete_house_22(offline)
    screen_name = image.get_attribute("aria-label")
    offline.emulate_media(media="print")
    assert image.is_visible() and image.get_attribute("aria-label") == screen_name
    assert offline.locator(".boundary-source").is_visible()
    for field in ("source", "table_id", "vintage", "geography", "method"):
        for cell in offline.locator(f'.figure dl.citation [data-field="{field}"]').all():
            assert cell.is_visible() and cell.inner_text().strip()
    assert pdf_pages(offline) == 1
    offline.pdf(
        path=str(tmp_path / f"{district.replace('/', '-')}-{variant or 'memo'}.pdf"),
        prefer_css_page_size=True,
    )


@pytest.mark.parametrize("district", ["house/22", "senate/5"])
@pytest.mark.parametrize("variant", ["", "a", "b"])
def test_outline_and_attribution_leave_print_room_for_wider_fonts(
    offline: Page, district: str, variant: str, tmp_path: Path
) -> None:
    """State attribution must fit with the complete brief even when text widens."""
    offline.set_viewport_size({"width": 1440, "height": 900})
    offline.goto(f"http://kyd/brief/{district}" + (f"?v={variant}" if variant else ""))
    offline.add_style_tag(content=".brief, .site-footer { letter-spacing: 0.04em; }")
    offline.emulate_media(media="print")
    assert offline.locator(".district-outline").is_visible()
    assert offline.locator(".boundary-source").is_visible()
    offline.pdf(
        path=str(tmp_path / f"wide-{district.replace('/', '-')}-{variant or 'memo'}.pdf"),
        prefer_css_page_size=True,
    )
    assert pdf_pages(offline) == 1


@pytest.mark.parametrize("coastlines", [False, True])
def test_multi_island_geometry_and_missing_coastline_fixture(
    offline: Page, monkeypatch: pytest.MonkeyPatch, coastlines: bool
) -> None:
    store = load_boundaries()
    boundary = store.district("house:15:013:2022")
    islands: list[IslandBoundary] = []
    for index, island in enumerate(boundary.islands):
        # Distinct synthetic rectangles: all four layers must actually render separately.
        west = -157.5 + index * 0.5
        shape = MultiPolygon(
            type="MultiPolygon",
            coordinates=[
                [
                    [
                        (west, 20.5),
                        (west + 0.3, 20.5),
                        (west + 0.3, 20.8),
                        (west, 20.8),
                        (west, 20.5),
                    ]
                ]
            ],
        )
        source = Available.model_validate(
            {
                "status": "available",
                "source": {
                    "service_url": "https://geodata.hawaii.gov/synthetic",
                    "layer_id": 1,
                    "retrieved_on": "2026-10-28",
                    "credit": "Synthetic coastline fixture",
                },
            }
        )
        islands.append(
            island.model_copy(update={"geometry": shape, "coastline": source})
            if coastlines
            else island.model_copy(
                update={
                    "geometry": None,
                    "coastline": Unavailable(
                        status="unavailable", reason="Synthetic fixture with no coastline geometry."
                    ),
                }
            )
        )
    updated = boundary.model_copy(update={"islands": tuple(islands)})
    fixture = store.model_copy(update={"districts": {**store.districts, boundary.id: updated}})
    monkeypatch.setattr(headline, "load_boundaries", lambda: fixture)
    offline.goto("http://kyd/brief/house/13")
    name = "Hawaiʻi State House District 13; Maui; Kahoʻolawe; Lānaʻi; Molokaʻi"
    image = offline.get_by_role("img", name=name, exact=True)
    assert image.count() == 1 and image.is_visible()
    paths = image.locator("path")
    assert paths.count() == (5 if coastlines else 1)
    assert len(set(paths.evaluate_all("ps => ps.map(p => p.getAttribute('d'))"))) == paths.count()
    for index, island in enumerate(islands):
        assert island.name in offline.locator(".boundary-islands").inner_text()
        if coastlines:
            assert paths.nth(index).get_attribute("aria-label") == island.name
            assert paths.nth(index).evaluate(
                "p => getComputedStyle(p).fill"
            ) != paths.last.evaluate("p => getComputedStyle(p).fill")
            assert float(paths.nth(index).evaluate("p => getComputedStyle(p).opacity")) < 0.5
    if coastlines:
        boxes: list[dict[str, float]] = paths.evaluate_all(
            "ps => ps.slice(0, -1).map(p => { const b = p.getBBox();"
            " return {x:b.x, y:b.y, width:b.width, height:b.height}; })"
        )
        # Independent fixture oracle: equal rectangles, spaced 0.5° apart, each 0.3° wide.
        for left, right in pairwise(boxes):
            assert right["width"] == pytest.approx(left["width"], abs=0.0001)
            assert right["height"] == pytest.approx(left["height"], abs=0.0001)
            assert right["y"] == pytest.approx(left["y"], abs=0.0001)
            assert (right["x"] - left["x"]) / left["width"] == pytest.approx(5 / 3)
            assert 0.93 < left["width"] / left["height"] < 0.95
        assert "Synthetic coastline fixture" in offline.locator(".boundary-source").inner_text()
    assert paths.last.evaluate("p => p.getBBox().width > 0 && p.getBBox().height > 0")
    assert axe_problems(offline) == []
    offline.emulate_media(media="print")
    assert image.is_visible()
