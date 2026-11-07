"""WO144: responsive decorative strips keep their geometry and ink in print."""

import pytest  # noqa: F401  # pyright: ignore[reportUnusedImport] -- #283 deletes only the superseded test
from playwright.sync_api import (
    Locator,
    Page,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- #283 deletes only the superseded test
)

from tests.regressions.test_wo122_browser_checks import (
    axe_problems,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- #283 deletes only the superseded test
    base_url,
    browser,
    open_page,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- #283 deletes only the superseded test
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
