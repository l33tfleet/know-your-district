"""WO146: token-only directions render distinctly without changing default pages."""

import pytest
from playwright.sync_api import Page

from tests.regressions.test_wo122_browser_checks import (
    axe_problems,
    base_url,
    browser,
    keyboard_problems,
    open_page,
    page,
)

__all__ = ["base_url", "browser", "page"]
WIDTHS = (390, 1440)


def style(page: Page, selector: str, property_name: str) -> str:
    return page.locator(selector).first.evaluate(
        "(e, p) => getComputedStyle(e).getPropertyValue(p)", property_name
    )


@pytest.mark.parametrize("width", WIDTHS)
def test_directions_have_rendered_hierarchy_and_distinct_ink(
    page: Page, base_url: str, width: int
) -> None:
    rendered: list[tuple[str, ...]] = []
    for variant in ("", "a", "b"):
        open_page(page, base_url + "/brief/house/22" + (f"?v={variant}" if variant else ""), width)
        rendered.append(
            tuple(
                style(page, selector, prop)
                for selector, prop in (
                    ("body", "color"),
                    ("h1", "font-size"),
                    ("h2", "font-size"),
                    (".program-name", "font-family"),
                    (".source summary", "padding-top"),
                    (".program-official a", "color"),
                )
            )
        )
        if variant:
            assert page.locator("body").get_attribute("data-variant") == variant
            sizes = [float(style(page, s, "font-size")[:-2]) for s in ("h1", "h2", "h3")]
            assert sizes[0] > sizes[1] > sizes[2]
            assert float(style(page, ".source summary", "padding-top")[:-2]) > 0
    assert len({r[0] for r in rendered}) == 3, "directions must visibly change the ink"
    assert rendered[0][1:] != rendered[1][1:]
    assert rendered[1][1:] != rendered[2][1:]


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("variant", ("a", "b"))
def test_variants_accessible_with_readable_expanded_sources(
    page: Page, base_url: str, variant: str, width: int
) -> None:
    open_page(page, f"{base_url}/brief/house/22?v={variant}", width)
    assert keyboard_problems(page) == []
    page.locator("details").evaluate_all("nodes => nodes.forEach(e => e.open = true)")
    assert axe_problems(page) == []
    assert page.locator(".citation").count() > 0
    assert page.locator(".citation dd").evaluate_all(
        "nodes => nodes.every(e => e.clientWidth >= e.scrollWidth)"
    ), "expanded citation text must wrap inside its column"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for selector in (".citation", ".citation dd", ".source summary"):
        assert float(style(page, selector, "font-size")[:-2]) >= 13
    summary = page.locator(".source summary").first
    summary.focus()
    assert style(page, ".source summary", "outline-style") != "none"
    page.emulate_media(media="print")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("path", ("/", "/brief/house/22"))
def test_default_matches_captured_styles(page: Page, base_url: str, path: str, width: int) -> None:
    """Values captured in Chromium before adding variant rules; home has no variant routing."""
    open_page(page, base_url + path, width)
    assert page.locator("body").get_attribute("data-variant") is None
    assert style(page, "body", "font-family") == 'Georgia, "Times New Roman", serif'
    assert style(page, "body", "color") == "rgb(0, 0, 0)"
    assert style(page, "body", "background-color") == "rgb(255, 255, 255)"
    assert style(page, ".site-header", "padding-top") == "16px"
    assert style(page, "main", "max-width") == "736px"
    if path == "/":
        assert style(page, "h1", "font-size") == "32px"
        assert style(page, "select", "appearance") == "auto"
        assert style(page, "button", "font-size") == "13.3333px"
    else:
        assert style(page, "h1", "font-size") == "25.6px"
        assert style(page, "h2", "font-size") == "24px"
        assert style(page, ".program-name", "font-size") == "18.72px"
        assert style(page, ".source summary", "padding-top") == "0px"
        assert style(page, ".citation", "font-size") == "12px"
