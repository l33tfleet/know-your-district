"""#361: an inserted note editor owns focus without waiting for htmx settling."""

from playwright.sync_api import Page

from tests.regressions.test_journey_folder_notes import (
    add_in_browser,
    open_folder,
    secret,
)
from tests.regressions.test_journey_folder_save import live_folders
from tests.regressions.test_wo122_browser_checks import base_url, browser
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

__all__ = ["base_url", "browser", "config", "live_folders", "page", "secret", "shipped_facts"]


def test_note_editor_has_focus_immediately_even_with_delayed_settling(
    page: Page, live_folders: str
) -> None:
    open_folder(page, live_folders)
    body = "Saved outreach note about the next session."
    add_in_browser(page, body)
    add_in_browser(page, "Another outreach note.")

    page.evaluate("window.htmx.config.defaultSettleDelay = 60000")
    page.locator(".note", has_text=body).get_by_role("link", name="Edit note").click()
    editor = page.get_by_role("textbox", name="Edit this note")
    editor.wait_for(state="visible")
    assert editor.evaluate("element => document.activeElement === element")
    assert editor.input_value() == body
