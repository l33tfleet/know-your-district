"""WO144: responsive decorative strips keep their geometry and ink in print."""

import pytest
from playwright.sync_api import Locator, Page

from tests.regressions.test_wo122_browser_checks import (
    axe_problems,
    base_url,
    browser,
    open_page,
    page,
)

# Reuse the WO122 server and Chromium fixtures without modifying their source.
__all__ = ["base_url", "browser", "page"]


def strip_ink(strip: Locator) -> list[dict[str, str]]:
    """Compare rendered geometry and ink without page-offset antialiasing noise."""
    return strip.evaluate(
        "e => [e, ...e.querySelectorAll('*')].map(n => {"
        " const s = getComputedStyle(n), b = n.getBBox();"
        " return {markup: n.outerHTML, box: JSON.stringify([b.x,b.y,b.width,b.height]),"
        " display: s.display, visibility: s.visibility, opacity: s.opacity,"
        " fill: s.fill, stroke: s.stroke, strokeWidth: s.strokeWidth, r: s.r,"
        " font: s.font, width: s.width, height: s.height}; })"
    )


@pytest.mark.parametrize("width", (390, 768, 1440))
def test_strip_accessibility_and_print_match(page: Page, base_url: str, width: int) -> None:
    open_page(page, base_url + "/brief/house/22", width)
    strips = page.locator("svg.interval-strip")
    assert strips.count() == 3
    assert axe_problems(page) == []
    assert page.locator('svg.interval-strip[aria-hidden="true"][focusable="false"]').count() == 3
    assert page.locator("svg.interval-strip[tabindex]").count() == 0
    for strip in strips.all():
        box = strip.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
    district = strips.first.locator('[data-role="district"] circle')
    state = strips.first.locator('[data-role="state"] circle')
    assert float(district.evaluate("e => getComputedStyle(e).r").removesuffix("px")) > float(
        state.evaluate("e => getComputedStyle(e).r").removesuffix("px")
    )
    screen = [strip_ink(strip) for strip in strips.all()]
    page.emulate_media(media="print")
    assert [strip_ink(strip) for strip in strips.all()] == screen
