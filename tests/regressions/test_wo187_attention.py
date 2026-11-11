"""WO187: reopening folders, with the plain folder wording.

Each test here is a copy of a superseded test in test_journey_attention.py, changed only where it pinned
the old words ("Priority: X. Status: Y." is now "Priority is X. Status is Y."; the note
hint and confirmation now say "groups of people, not one resident"). Every check of
behaviour, storage, isolation, focus and accessibility is kept as it was.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.regressions.test_journey_folder_save import client, flag
from tests.regressions.test_wo122_browser_checks import base_url, browser
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo_step5_save_priority import live_shipped

__all__ = [
    "base_url",
    "browser",
    "client",
    "config",
    "flag",
    "live_shipped",
    "page",
    "shipped_facts",
]


# Replaces test_journey_attention.py::test_browser_reopening_two_folders_reflects_each_saved_state (wording only, #187).
def test_browser_reopening_two_folders_reflects_each_saved_state(
    page: Page, live_shipped: str
) -> None:
    paths: list[str] = []
    for _ in range(2):
        page.goto(f"{live_shipped}/brief/house/22")
        page.get_by_role("button", name="Save to folder").click()
        page.wait_for_url("**/f/*")
        paths.append(page.url)
        expect(page.get_by_role("region", name="Needs attention", exact=True)).to_be_visible()
    page.goto(paths[0])
    page.select_option("select[name=priority]", "high")
    page.get_by_text("Priority is High. Status is Idea.", exact=True).wait_for()
    page.get_by_text("Reopen this folder's link", exact=True).click()
    attention = page.get_by_role("region", name="Needs attention", exact=True)
    expect(attention).to_contain_text("Make first contact")
    expect(attention).to_contain_text("High priority, still an idea")
    expect(attention.get_by_role("link")).to_contain_text("SNAP")
    page.select_option("select[name=status]", "done")
    page.get_by_text("Priority is High. Status is Done.", exact=True).wait_for()
    page.get_by_text("Reopen this folder's link", exact=True).click()
    expect(attention).to_contain_text("Nothing needs attention")

    page.goto(paths[1])
    page.reload()
    expect(attention).to_contain_text("Normal priority, status idea")
    expect(attention).not_to_contain_text("Make first contact")
    expect(attention.locator("li")).to_have_count(1)
    page.goto(paths[0])
    page.reload()
    expect(attention.locator("li")).to_have_count(0)
    expect(attention).to_contain_text("Nothing needs attention")


# Replaces test_journey_attention.py::test_story_steps_5_to_7_refresh_confirmed_notes_in_separate_folders (wording only, #187).
def test_story_steps_5_to_7_refresh_confirmed_notes_in_separate_folders(
    page: Page, live_shipped: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KYD_FOLDERS_SECRET", "attention-browser-test-secret-32-bytes")
    paths: list[str] = []
    attention = page.get_by_role("region", name="Needs attention", exact=True)
    for _ in range(2):
        page.goto(f"{live_shipped}/brief/house/22")
        page.get_by_role("region", name="SNAP", exact=True).get_by_role(
            "button", name="Save to folder"
        ).click()
        page.wait_for_url("**/f/*")
        paths.append(page.url)
    page.goto(paths[0])
    page.get_by_role("combobox", name="Priority").select_option(label="High")
    page.get_by_text("Priority is High. Status is Idea.", exact=True).wait_for()
    page.get_by_role("combobox", name="Status").select_option(label="Planned")
    page.get_by_text("Priority is High. Status is Planned.", exact=True).wait_for()
    expect(page.get_by_text("Saved").first).to_be_visible()
    page.get_by_role("textbox", name="Add a note", exact=True).fill(
        "Table at Mōʻiliʻili meeting 11/8"
    )
    page.get_by_role("button", name="Add note", exact=True).click()
    expect(page.get_by_text("Table at Mōʻiliʻili meeting 11/8", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save note", exact=True).click()
    expect(page.locator(".note-body")).to_have_text("Table at Mōʻiliʻili meeting 11/8")
    page.get_by_role("link", name="Open the office folder", exact=True).click()
    page.reload()
    expect(attention).to_contain_text("High priority, status planned")
    page.get_by_role("button", name="What needs attention?", exact=True).click()
    expect(attention).to_be_visible()
    expect(attention).to_contain_text("SNAP")
    expect(attention).to_contain_text("0 days since the last note")
    expect(page.locator(".note-body")).to_have_text("Table at Mōʻiliʻili meeting 11/8")
    page.goto(paths[1])
    page.get_by_role("link", name="Open the office folder", exact=True).click()
    page.reload()
    page.get_by_role("button", name="What needs attention?", exact=True).click()
    expect(attention).to_contain_text("Normal priority, status idea")
    expect(attention).to_contain_text("no notes")
    expect(page.locator(".note-body")).to_have_count(0)
    page.goto(paths[0])
    page.get_by_role("button", name="What needs attention?", exact=True).click()
    expect(attention).to_contain_text("High priority, status planned")
    expect(attention).to_contain_text("0 days since the last note")
