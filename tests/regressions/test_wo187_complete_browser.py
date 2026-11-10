"""WO187: retain the complete folder journey with the revised display wording.

Only the summary and note confirmation prose changes; all behavior checks remain.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.copy import section_copy
from app.folders.notes import date_label
from tests.regressions.test_journey_folder_save import (
    HTMX,
    card_id,
    client,
    create,
    flag,
    live_folders,
    post,
)
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, pdf_pages, shipped_facts
from tests.regressions.test_wo153_complete_browser import (
    BRIEF,
    mark_document,
    oob,
    printed_rows,
    same_document,
)
from tests.regressions.test_wo187_folder_notes import add_in_browser

__all__ = [
    "base_url",
    "browser",
    "client",
    "config",
    "flag",
    "live_folders",
    "page",
    "shipped_facts",
]


# Replaces test_wo153_complete_browser.py::test_a_status_write_refreshes_the_summary_and_keeps_the_card_swap (wording only, #187).
def test_a_status_write_refreshes_the_summary_and_keeps_the_card_swap(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    response = post(client, f"{path}/cards/{card}/status", "status=planned", HTMX)
    refreshed = oob(response.text, "folder-print")
    assert "Planned · Normal priority" in refreshed.text
    # The card's own summary is still in the answer for its `hx-select`.
    assert f'id="summary-{card}"' in response.text
    assert "Status is Planned." in parse(response.text).one("p", id=f"summary-{card}").text


# Replaces test_wo153_complete_browser.py::test_browser_complete_journey_create_to_print (wording only, #187).
def test_browser_complete_journey_create_to_print(page: Page, live_folders: str) -> None:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 1440)
    page.get_by_role("button", name=section_copy("case")["save_label"]).click()  # create, save
    page.wait_for_url("**/f/*")
    url = page.url
    mark_document(page)

    page.get_by_role("combobox", name="Status").select_option(label="Planned")  # status
    page.locator("#folder-print", has_text="Planned · Normal priority").wait_for()
    page.get_by_role("combobox", name="Priority").select_option(label="High")
    page.fill("input[name=reason]", "Office outreach week")
    page.locator("input[name=reason]").press("Tab")
    page.locator(
        "#folder-print", has_text="Planned · High priority · Office outreach week"
    ).wait_for()
    page.locator("#folder-retention", has_text="deleted on").wait_for()

    add_in_browser(page, "First outreach note.")  # add
    today = date_label(datetime.now(UTC).date().isoformat())
    page.locator("#folder-print", has_text=f"Notes: 1, newest dated {today}").wait_for()
    note = page.locator(".note", has_text="First outreach note.")
    note.get_by_role("link", name="Edit note").click()  # edit
    page.get_by_role("textbox", name="Edit this note").fill("First note, edited.")
    page.get_by_role("button", name="Update note").click()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-body", has_text="First note, edited.").wait_for()

    page.locator("button.copy-link").click()  # copy
    page.get_by_text("Link copied").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == url
    assert same_document(page) and page.url == url  # every write was an htmx partial
    assert axe_problems(page) == []

    page.get_by_role("link", name="Reopen this folder's link").click()  # reopen
    page.wait_for_load_state("load")
    assert printed_rows(page)[0].endswith(
        f"Planned · High priority · Office outreach week Notes: 1, newest dated {today}."
    )

    page.emulate_media(media="print")  # print
    assert page.locator("#folder-print").is_visible()
    assert page.locator(".folder-card").first.is_hidden()
    assert page.locator(".folder-notes").first.is_hidden()
    assert page.locator("#folder-retention").is_visible()
    assert pdf_pages(page) == 1
    page.emulate_media(media="screen")
    assert axe_problems(page) == []
