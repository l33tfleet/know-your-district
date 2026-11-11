"""#361: an inserted note editor owns focus without waiting for htmx settling."""

from playwright.sync_api import Page  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded

from tests.regressions.test_journey_folder_notes import (
    add_in_browser,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    open_folder,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    secret,
)
from tests.regressions.test_journey_folder_save import live_folders
from tests.regressions.test_wo122_browser_checks import base_url, browser
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

__all__ = ["base_url", "browser", "config", "live_folders", "page", "secret", "shipped_facts"]
