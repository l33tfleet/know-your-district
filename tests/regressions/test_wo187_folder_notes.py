"""WO187: folder notes, with the plain folder wording.

Each test here is a copy of a superseded test in test_journey_folder_notes.py, test_wo378_note_confirmation_focus.py and test_wo361_note_editor_focus.py, changed only where it pinned
the old words ("Priority: X. Status: Y." is now "Priority is X. Status is Y."; the note
hint and confirmation now say "groups of people, not one resident"). Every check of
behaviour, storage, isolation, focus and accessibility is kept as it was.
"""

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Locator, Page

from tests.regressions.test_journey_folder_notes import (
    BRIEF,
    NOTE,
    PERSONAL,
    SAMPLES,
    WORDS,
    all_bodies,
    browser_notes,
    check,
    folder,
    live_bodies,
    notes_endpoint,
    open_folder,
    secret,
    shown,
    token_in,
)
from tests.regressions.test_journey_folder_save import card_id, client, flag, live_folders, post
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo_step5_save_priority import live_shipped

__all__ = [
    "BRIEF",
    "NOTE",
    "PERSONAL",
    "SAMPLES",
    "WORDS",
    "all_bodies",
    "axe_problems",
    "base_url",
    "browser",
    "browser_notes",
    "card_id",
    "check",
    "client",
    "config",
    "flag",
    "folder",
    "live_bodies",
    "live_folders",
    "live_shipped",
    "notes_endpoint",
    "open_folder",
    "open_page",
    "page",
    "parse",
    "post",
    "secret",
    "shipped_facts",
    "shown",
    "token_in",
]

HINT = "Notes are about outreach and groups of people, not one resident."
CONFIRM = "This note is about outreach and groups of people, not one resident."


# Copy of test_journey_folder_notes.py::add_in_browser, with the #187 wording.
def add_in_browser(page: Page, body: str) -> None:
    page.get_by_role("textbox", name="Add a note").fill(body)
    page.get_by_role("button", name="Add note").click()
    page.get_by_text(CONFIRM).wait_for()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.locator(".note-body", has_text=body).wait_for()


# Copy of test_wo378_note_confirmation_focus.py::entry, with the #187 wording.
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


# Replaces test_journey_folder_notes.py::test_a_clean_note_needs_the_confirm_step_before_it_saves (wording only, #187).
def test_a_clean_note_needs_the_confirm_step_before_it_saves(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    endpoint = notes_endpoint(client, folder)
    checked = check(client, endpoint, NOTE)
    assert checked.status_code == 200
    assert CONFIRM in checked.text
    assert token_in(checked.text) is not None
    assert all_bodies(tmp_path) == []

    saved = post(
        client, endpoint, urlencode({"body": NOTE, "confirmation": token_in(checked.text)})
    )
    assert (saved.status_code, saved.headers["location"]) == (303, folder)
    assert live_bodies(tmp_path) == [NOTE]
    assert NOTE in shown(client, folder)


# Replaces test_journey_folder_notes.py::test_the_box_is_labelled_described_and_bounded (wording only, #187).
def test_the_box_is_labelled_described_and_bounded(client: TestClient, folder: str) -> None:
    card = card_id(client, folder)
    document = parse(client.get(folder).text)
    box = document.one("textarea", id=f"note-new-{card}")
    assert box.attrs["maxlength"] == "1000"
    assert box.attrs["name"] == "body"
    assert document.one("label", **{"for": f"note-new-{card}"}).text.strip() == "Add a note"
    hint = document.one("p", id=box.attrs["aria-describedby"])
    assert hint.text.strip() == HINT
    section = document.one("section", id=f"notes-{card}")
    assert section.attrs["aria-labelledby"] == f"notes-heading-{card}"


# Replaces test_journey_folder_notes.py::test_browser_adds_edits_and_deletes_and_order_survives_a_reload (wording only, #187).
def test_browser_adds_edits_and_deletes_and_order_survives_a_reload(
    page: Page, live_folders: str
) -> None:
    open_folder(page, live_folders)
    url = page.url
    assert HINT in page.inner_text("main")
    add_in_browser(page, "First outreach note.")
    add_in_browser(page, "Second outreach note.")
    add_in_browser(page, "Third outreach note.")
    assert page.url == url  # htmx partial updates, not page loads
    assert browser_notes(page) == [
        "Third outreach note.",
        "Second outreach note.",
        "First outreach note.",
    ]

    second = page.locator(".note", has_text="Second outreach note.")
    second.get_by_role("link", name="Edit note").click()
    box = page.get_by_role("textbox", name="Edit this note")
    box.wait_for()
    assert page.evaluate("document.activeElement.id") == box.get_attribute("id")
    assert box.input_value() == "Second outreach note."
    box.fill("Second note, edited.")
    page.get_by_role("button", name="Update note").click()
    page.get_by_text(CONFIRM).wait_for()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.locator(".note-body", has_text="Second note, edited.").wait_for()

    page.locator(".note", has_text="First outreach note.").get_by_role(
        "button", name="Delete note"
    ).click()
    page.locator(".note-body", has_text="First outreach note.").wait_for(state="detached")
    assert axe_problems(page) == []

    page.reload()
    assert browser_notes(page) == ["Third outreach note.", "Second note, edited."]
    dates = page.locator(".note time").all()
    assert len(dates) == 2
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.get_attribute("datetime") or "") for d in dates)
    assert all(d.inner_text().strip() for d in dates)
    assert axe_problems(page) == []


# Replaces test_journey_folder_notes.py::test_browser_keyboard_alone_adds_a_note (wording only, #187).
def test_browser_keyboard_alone_adds_a_note(page: Page, live_folders: str) -> None:
    open_folder(page, live_folders, 390)
    page.get_by_role("textbox", name="Add a note").focus()
    page.keyboard.type("Keyboard outreach note.")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Add note"
    page.keyboard.press("Enter")
    page.get_by_text(CONFIRM).wait_for()
    assert page.evaluate("document.activeElement.textContent.trim()") == "Save note"
    page.keyboard.press("Enter")
    page.locator(".note-confirm").wait_for(state="detached")
    page.locator(".note-body", has_text="Keyboard outreach note.").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


# Replaces test_journey_folder_notes.py::test_story_steps_5_and_6_run_as_written_on_the_shipped_flags (wording only, #187).
def test_story_steps_5_and_6_run_as_written_on_the_shipped_flags(
    page: Page, live_shipped: str
) -> None:
    """Decisions §16: step 6 runs inside step 5's segment, on the committed `features.toml`
    and without `?preview=1`; the note shows once "Add note" is pressed."""
    open_page(page, f"{live_shipped}{BRIEF}", 1440)
    region = page.get_by_role("region", name="SNAP", exact=True)
    region.get_by_role("button", name="Save to folder").click()
    page.wait_for_url("**/f/*")
    assert "preview" not in page.url
    page.get_by_role("combobox", name="Priority").select_option(label="High")
    page.get_by_text("Priority is High. Status is Idea.", exact=True).wait_for()
    page.get_by_role("combobox", name="Status").select_option(label="Planned")
    page.get_by_text("Priority is High. Status is Planned.", exact=True).wait_for()

    page.get_by_role("textbox", name="Add a note").fill("Table at Mōʻiliʻili meeting 11/8")
    page.get_by_role("button", name="Add note").click()
    page.get_by_text("Table at Mōʻiliʻili meeting 11/8").first.wait_for()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.reload()
    assert browser_notes(page) == ["Table at Mōʻiliʻili meeting 11/8"]


# Replaces test_journey_folder_notes.py::test_demo_steps_run_as_written (wording only, #187).
def test_demo_steps_run_as_written(page: Page, live_folders: str) -> None:
    """The commit's `Demo:` block, step for step, on the shipped `preview` flag."""
    page.goto(f"{live_folders}/brief/house/22?preview=1")
    page.click("text=Save to folder")
    page.get_by_text(HINT).wait_for()
    page.fill("textarea[name=body]", "Tabled at the Kalihi farmers market.")
    page.click("text=Add note")
    page.get_by_text(CONFIRM).wait_for()
    page.click("text=Save note")
    page.locator(".note-confirm").wait_for(state="detached")
    page.click("text=Reopen this folder's link")
    page.wait_for_load_state("load")
    page.get_by_text("Tabled at the Kalihi farmers market.").wait_for()


# Replaces test_journey_folder_notes.py::test_story_step_6_shows_the_note_the_moment_add_note_is_pressed (wording only, #187).
def test_story_step_6_shows_the_note_the_moment_add_note_is_pressed(
    page: Page, live_shipped: str
) -> None:
    """The story runner checks step 6 once, right after the click, with no wait (its record
    of a97437e: the check request took about a second, so the page still showed an empty box).
    The typed words show at once, as a status, while the server checks them."""
    open_page(page, f"{live_shipped}{BRIEF}", 1440)
    page.get_by_role("region", name="SNAP", exact=True).get_by_role(
        "button", name="Save to folder"
    ).click()
    page.wait_for_url("**/f/*")
    held: list[Any] = []
    page.route("**/cards/*/notes*", lambda route: held.append(route))
    words = "Table at Mōʻiliʻili meeting 11/8"
    page.get_by_role("textbox", name="Add a note").fill(words)
    page.get_by_role("button", name="Add note").click()
    status = page.get_by_role("region", name="Notes").get_by_role("status")
    assert words in page.locator("body").inner_text()
    assert words in status.inner_text()
    assert WORDS["checking_note"] in status.inner_text()
    for route in held:
        route.continue_()
    page.get_by_text(CONFIRM).wait_for()
    assert WORDS["checking_note"] not in page.locator("body").inner_text()


# Replaces test_wo378_note_confirmation_focus.py::test_keyboard_confirmation_focus_is_immediate_and_save_survives_reload (wording only, #187).
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


# Replaces test_wo378_note_confirmation_focus.py::test_keyboard_refusal_focus_is_immediate_and_personal_text_is_not_saved (wording only, #187).
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


# Replaces test_wo361_note_editor_focus.py::test_note_editor_has_focus_immediately_even_with_delayed_settling (wording only, #187).
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
