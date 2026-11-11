"""WO187: saving on change, with the plain folder wording.

Each test here is a copy of a superseded test in test_wo_step5_save_on_change.py, changed only where it pinned
the old words ("Priority: X. Status: Y." is now "Priority is X. Status is Y."; the note
hint and confirmation now say "groups of people, not one resident"). Every check of
behaviour, storage, isolation, focus and accessibility is kept as it was.
"""

from pathlib import Path

from playwright.sync_api import Page

from tests.regressions.test_journey_folder_save import (
    BRIEF,
    COPY,
    NOTICE,
    STATE_DIR,
    client,
    db,
    flag,
    live_folders,
)
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

__all__ = [
    "BRIEF",
    "COPY",
    "NOTICE",
    "STATE_DIR",
    "base_url",
    "browser",
    "client",
    "config",
    "db",
    "flag",
    "live_folders",
    "open_page",
    "page",
    "shipped_facts",
]


# Replaces test_wo_step5_save_on_change.py::test_keyboard_change_saves_and_keeps_focus_on_the_select (wording only, #187).
def test_keyboard_change_saves_and_keeps_focus_on_the_select(page: Page, live_folders: str) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 390)
    page.get_by_role("button", name=COPY["save_label"]).focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/f/*")

    page.focus("select[name=status]")
    page.keyboard.press("ArrowDown")
    page.get_by_text("Status is contacted").wait_for()
    assert page.evaluate("document.activeElement.name") == "status"
    assert page.evaluate("document.activeElement.tagName") == "SELECT"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


# Replaces test_wo_step5_save_on_change.py::test_demo_steps_run_as_written (wording only, #187).
def test_demo_steps_run_as_written(page: Page, live_folders: str, tmp_path: Path) -> None:
    """The commit's `Demo:` block, step for step, on the shipped `preview` flag."""
    page.goto(f"{live_folders}/brief/house/22?preview=1")
    page.click("text=Save to folder")
    page.get_by_text(NOTICE).wait_for()
    page.select_option("select[name=priority]", "high")
    page.get_by_text("Priority is high").wait_for()
    page.select_option("select[name=status]", "planned")
    page.get_by_text("Status is planned").wait_for()
    page.click("text=Reopen this folder's link")
    page.get_by_text("Priority is high. Status is planned.").wait_for()
    assert (tmp_path / STATE_DIR / "folders.db").exists()
