"""#378: confirmation and refusal focus must arrive with the visible response."""

import pytest
from playwright.sync_api import Locator, Page

from tests.regressions.test_journey_folder_notes import (
    CONFIRM,
    PERSONAL,
    SAMPLES,
    add_in_browser,
    browser_notes,
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


@pytest.mark.parametrize("editing", [False, True], ids=["add", "update"])
def test_keyboard_confirmation_focus_is_immediate_and_save_survives_reload(
    page: Page, live_folders: str, editing: bool
) -> None:
    box = entry(page, live_folders, editing)
    body = "Keyboard outreach note."
    box.fill(body)
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    page.get_by_text(CONFIRM, exact=True).wait_for(state="visible")
    save = page.get_by_role("button", name="Save note", exact=True)
    assert save.evaluate("element => document.activeElement === element")
    page.keyboard.press("Enter")
    page.locator(".note-body", has_text=body).wait_for(state="visible")
    page.reload()
    assert browser_notes(page) == ([body] if editing else [body, "Original outreach note."])


@pytest.mark.parametrize("editing", [False, True], ids=["add", "update"])
def test_keyboard_refusal_focus_is_immediate_and_personal_text_is_not_saved(
    page: Page, live_folders: str, editing: bool
) -> None:
    box = entry(page, live_folders, editing)
    box.fill(SAMPLES["phone"])
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    page.get_by_role("alert").get_by_text(PERSONAL, exact=True).wait_for(state="visible")
    assert box.evaluate("element => document.activeElement === element")
    assert box.get_attribute("aria-invalid") == "true"
    assert box.input_value() == SAMPLES["phone"]
    assert page.get_by_role("button", name="Save note", exact=True).count() == 0
    page.reload()
    assert browser_notes(page) == ["Original outreach note."]
