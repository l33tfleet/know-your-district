"""WO201: offline browser coverage for outlines, both coastline states and print."""

import importlib
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page

from app.boundary_store import BoundaryStore, load_boundaries
from etl.boundaries import MultiPolygon
from etl.islands import Available, CoastlineSource
from tests.regressions.test_wo122_browser_checks import (
    axe_problems,
    base_url,
    browser,
    open_page,
    page,
)
from tests.regressions.test_wo143_integration import config, live_config, shipped_facts

__all__ = ["base_url", "browser", "config", "live_config", "page", "shipped_facts"]


@pytest.mark.parametrize("chamber,number", [("house", 22), ("senate", 5)])
@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
def test_outline_keeps_complete_brief_on_one_printed_page(
    page: Page,
    shipped_facts: str,
    live_config: Path,
    chamber: str,
    number: int,
    variant: str,
    tmp_path: Path,
) -> None:
    """The outline and attribution leave room for full facts, even with wider text."""
    open_page(page, f"{shipped_facts}/brief/{chamber}/{number}{variant}", 1440)
    page.add_style_tag(content=".brief, .site-footer { letter-spacing: 0.04em; }")
    page.emulate_media(media="print")
    assert page.locator(".district-outline svg").is_visible()
    assert page.locator(".boundary-source").is_visible()
    pdf = page.pdf(path=str(tmp_path / "brief.pdf"), prefer_css_page_size=True)
    assert len(re.findall(rb"/Type\s*/Page(?!s)", pdf)) == 1


@pytest.mark.parametrize("chamber,number", [("house", 22), ("senate", 8)])
@pytest.mark.parametrize("width", [390, 768, 1440])
def test_chambers_mobile_accessibility_and_print(
    page: Page, base_url: str, chamber: str, number: int, width: int, tmp_path: Path
) -> None:
    open_page(page, f"{base_url}/brief/{chamber}/{number}", width)
    svg = page.locator(".brief-headline svg")
    assert svg.count() == 1
    assert svg.is_visible()
    assert page.get_by_role("img", name=svg.get_attribute("aria-label"), exact=True).count() == 1
    boundary = load_boundaries().district(f"{chamber}:15:{number:03}:2022")
    assert svg.locator("path").count() == 1 + sum(i.geometry is not None for i in boundary.islands)
    assert axe_problems(page) == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    title_box = page.locator("h1").bounding_box()
    map_box = svg.bounding_box()
    assert title_box is not None and map_box is not None
    assert map_box["x"] >= title_box["x"] + title_box["width"]
    assert map_box["y"] < title_box["y"] + title_box["height"]
    assert map_box["width"] > 40 and map_box["height"] > 30
    page.emulate_media(media="print")
    assert svg.is_visible() and svg.locator("path").last.is_visible()
    assert svg.locator("path").last.evaluate("p => getComputedStyle(p).fill") != "none"
    pdf = page.pdf(path=str(tmp_path / f"{chamber}-{number}.pdf"), prefer_css_page_size=True)
    assert len(re.findall(rb"/Type\s*/Page(?!s)", pdf)) == 1


@pytest.mark.parametrize("coastlines", [True, False])
def test_multi_island_fixture_with_and_without_coastlines(
    page: Page, base_url: str, monkeypatch: pytest.MonkeyPatch, coastlines: bool
) -> None:
    store = load_boundaries()
    boundary = store.district("house:15:013:2022")
    source = CoastlineSource.model_validate_json(
        (Path(__file__).parent / "fixtures/wo145_islands/coastline.source.json").read_text()
    )
    # Synthetic, deliberately distinct island shapes. Production geometry stays untouched.
    islands = tuple(
        island.model_copy(
            update={
                "geometry": MultiPolygon(
                    type="MultiPolygon",
                    coordinates=[
                        [[(-158 + n, 20), (-157.5 + n, 20), (-157.5 + n, 21), (-158 + n, 20)]]
                    ],
                )
                if coastlines
                else None,
                "coastline": Available(status="available", source=source)
                if coastlines
                else island.coastline,
            }
        )
        for n, island in enumerate(boundary.islands)
    )
    fixture = BoundaryStore(
        districts={
            **store.districts,
            boundary.id: boundary.model_copy(update={"islands": islands}),
        }
    )
    headline = importlib.import_module("app.sections.10_headline")
    monkeypatch.setattr(headline, "load_boundaries", lambda: fixture)
    open_page(page, base_url + "/brief/house/13", 390)
    svg = page.locator(".brief-headline svg")
    assert svg.count() == 1
    assert svg.is_visible()
    label = svg.get_attribute("aria-label")
    assert label is not None
    assert page.get_by_role("img", name=label, exact=True).count() == 1
    names = ["Maui", "Kahoʻolawe", "Lānaʻi", "Molokaʻi"]
    assert all(name in label for name in names)
    paths = svg.locator("path")
    assert paths.count() == (5 if coastlines else 1)
    if coastlines:
        assert [paths.nth(i).get_attribute("aria-label") for i in range(4)] == names
        assert all(paths.nth(i).is_visible() for i in range(4))
        assert paths.nth(0).evaluate("p => getComputedStyle(p).fill") != paths.last.evaluate(
            "p => getComputedStyle(p).fill"
        )
        assert all(
            0 < float(paths.nth(i).evaluate("p => getComputedStyle(p).fillOpacity")) < 0.5
            for i in range(4)
        )
    assert "House District 13" in (paths.last.get_attribute("aria-label") or "")
    assert float(paths.last.evaluate("p => getComputedStyle(p).fillOpacity")) == 1
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert all(paths.nth(i).is_visible() for i in range(paths.count()))
