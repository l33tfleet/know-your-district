"""WO261 step 2 (#283): with the strip gone, figures stay accessible and print as on screen.

Replaces `test_wo144_browser.py::test_strip_accessibility_and_print_match`: at each width the
brief has no serious axe problems, three figure boxes inside the viewport, and each figure's
computed box styles are the same on screen and in print. Height is left out: the citation
`<details>` prints open, so the box is legitimately taller on paper.
"""

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

STYLES = (
    "display",
    "visibility",
    "color",
    "font",
    "width",
    "marginTop",
    "marginRight",
    "marginBottom",
    "marginLeft",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "borderTop",
    "borderRight",
    "borderBottom",
    "borderLeft",
)


def box_styles(figure: Locator) -> dict[str, str]:
    return figure.evaluate(
        "(e, keys) => { const s = getComputedStyle(e);"
        " return Object.fromEntries(keys.map(k => [k, s[k]])); }",
        list(STYLES),
    )


@pytest.mark.parametrize("width", (390, 768, 1440))
def test_figures_accessible_in_viewport_and_print_match(
    page: Page, base_url: str, width: int
) -> None:
    open_page(page, base_url + "/brief/house/22", width)
    assert page.locator("svg.interval-strip").count() == 0
    assert axe_problems(page) == []
    figures = page.locator(".figure")
    assert figures.count() == 3
    for figure in figures.all():
        box = figure.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
    screen = [box_styles(f) for f in figures.all()]
    page.emulate_media(media="print")
    assert [box_styles(f) for f in figures.all()] == screen


def test_house_43_renders_figures_without_any_strip(page: Page, base_url: str) -> None:
    """The work order's evidence page, as Chromium paints it: figures with readings, no dots."""
    open_page(page, base_url + "/brief/house/43", 1440)
    figures = page.locator(".figure")
    assert figures.count() == 3
    assert page.locator(".figure svg, svg.interval-strip").count() == 0
    for figure in figures.all():
        reading = figure.locator(".reading").first
        assert reading.is_visible()
        # The wo122 server's fixture may lack this district: a reading is a value or "missing".
        assert reading.locator("data.value, .missing").count() == 1
