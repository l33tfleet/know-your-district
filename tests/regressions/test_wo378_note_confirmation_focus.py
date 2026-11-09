"""#378: confirmation and refusal focus must arrive with the visible response."""

import pytest  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from playwright.sync_api import Locator, Page

from tests.regressions.test_journey_folder_notes import (
    CONFIRM,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    PERSONAL,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    SAMPLES,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    add_in_browser,
    browser_notes,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    open_folder,
    secret,
)
from tests.regressions.test_journey_folder_save import live_folders
from tests.regressions.test_wo122_browser_checks import base_url, browser
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

__all__ = ["base_url", "browser", "config", "live_folders", "page", "secret", "shipped_facts"]


def entry(page: Page, base: str, editing: bool) -> Locator:
    open_folder(page, base)
    page.wait_for_load_state("load")
    # Exercise a subsequent response, after native browser autofocus has already run.
    add_in_browser(page, "Original outreach note.")
    if editing:
        page.get_by_role("link", name="Edit note", exact=True).click()
    box = page.get_by_role("textbox", name="Edit this note" if editing else "Add a note")
    box.wait_for(state="visible")
    page.evaluate("window.htmx.config.defaultSettleDelay = 60000")
    return box
