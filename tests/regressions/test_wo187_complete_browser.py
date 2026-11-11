"""WO187: retain the complete folder journey with the revised display wording.

Only the summary and note confirmation prose changes; all behavior checks remain.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.copy import load_copy, section_copy
from app.folders import routes as folder_routes
from app.folders import store
from app.folders.notes import date_label
from app.folders.references import encode_match
from tests.regressions.test_journey_folder_save import (
    HTMX,
    card_id,
    client,
    create,
    flag,
    live_folders,
    post,
    state,
)
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, pdf_pages, shipped_facts
from tests.regressions.test_wo153_complete_browser import (
    BRIEF,
    disclosures,
    fill_with_matches,
    mark_document,
    match,
    matched,
    oob,
    printed_rows,
    rows,
    same_document,
    summary,
)
from tests.regressions.test_wo187_folder_notes import add_in_browser

__all__ = [
    "base_url",
    "browser",
    "client",
    "config",
    "flag",
    "live_folders",
    "matched",
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


# --- saved match labels: program and population now end as two short sentences (#187) ---

WORDS = load_copy()["folders"]
# The published match labels, as `card_names` writes them; the SNAP one is the longest shipped.
ABLE = "Hawaiʻi ABLE savings program. People with a disability"
PRE_K = "EOEL Public Pre-K. Children under 5"
SNAP_MATCH = (
    "Supplemental Nutrition Assistance Program (SNAP). Households below poverty reporting no SNAP"
)
# The legacy card, ABLE, Pre-K, then the SNAP match in Houses 1-9; Houses 10-22 are counted.
MATCHED_ROWS = [("SNAP", 22), (ABLE, 1), (PRE_K, 1)] + [(SNAP_MATCH, d) for d in range(1, 10)]


def identity(row: str) -> tuple[str, int]:
    """The label a printed row starts with and its district; an unknown label fails loudly."""
    found = re.search(r"Hawaiʻi State House District (\d+)", row)
    assert found is not None, row
    names = [
        n
        for n in (SNAP_MATCH, ABLE, PRE_K)
        if row.startswith(n) and row[len(n) :].lstrip().startswith(". ")
    ]
    if not names and row.startswith("SNAP"):
        names = ["SNAP"]
    assert len(names) == 1, row
    assert " · Hawaiʻi State House District" not in row  # the old run-on label is gone
    return names[0], int(found[1])


def test_labels_are_the_published_program_and_population_names() -> None:
    """The label constants are the catalog names joined as sentences, not hand-made text."""
    names = folder_routes.card_names(
        [
            store.Card(
                id=1,
                case_id=encode_match(match(population, program, 1)),
                chamber="house",
                district=1,
                status="idea",
                priority="normal",
                reason=None,
                created_at="2026-11-10T00:00:00+00:00",
                updated_at="2026-11-10T00:00:00+00:00",
            )
            for population, program in (
                ("disability", "hawaii-able"),
                ("children_under_5", "public-pre-k"),
                ("below_poverty_no_snap", "snap"),
            )
        ]
    )
    matched_names = {v for k, v in names.items() if k.startswith("match:")}
    assert matched_names == {ABLE, PRE_K, SNAP_MATCH}


# Replaces test_wo153_complete_browser.py::test_saved_matches_are_listed_by_their_published_labels (wording only, #187).
def test_saved_matches_are_listed_by_their_published_labels(
    matched: tuple[TestClient, str, store.FolderStore],
) -> None:
    http, path, _ = matched
    html = http.get(path).text
    listed = rows(html)
    assert [identity(row) for row in listed] == MATCHED_ROWS
    assert all("High priority" in row for row in listed)
    printed = summary(html)
    # The encoded selection key is storage only: never on paper.
    assert "match:v1" not in printed.text
    assert disclosures(html) == [
        WORDS["print_cards"].format(shown=12, total=25, omitted=13),
        WORDS["print_notes_omitted"].format(total=25),
        WORDS["print_shortened"].format(count=12),
    ]
    reasons = [r.text for r in printed.find_all("span", class_="folder-print-reason")]
    assert len(reasons) == 12
    assert all(r.endswith("…") and len(r) <= folder_routes.PRINT_REASON for r in reasons)
    assert not printed.find_all(class_="case") and not printed.find_all(class_="figure")
    assert "n" * 50 not in printed.text
    assert html.count('class="folder-card"') == 25


# Replaces test_wo153_complete_browser.py::test_a_match_card_write_refreshes_the_summary_with_its_identity (wording only, #187).
def test_a_match_card_write_refreshes_the_summary_with_its_identity(
    matched: tuple[TestClient, str, store.FolderStore],
) -> None:
    http, path, db = matched
    key = encode_match(match("disability", "hawaii-able", 1))
    cards = db.get_folder(path.rsplit("/", 1)[-1]).cards
    able = next(card for card in cards if card.case_id == key)
    response = post(http, f"{path}/cards/{able.id}/status", "status=done", HTMX)
    assert response.status_code == 200
    listed = [row.text for row in oob(response.text, "folder-print").find_all("li")]
    # Done sorts the ABLE card past the bound; the next SNAP match takes its place.
    assert (ABLE, 1) not in [identity(row) for row in listed]
    assert [identity(row) for row in listed][-1] == (SNAP_MATCH, 10)
    assert WORDS["print_cards"].format(shown=12, total=25, omitted=13) in (
        oob(response.text, "folder-print").text
    )


# Replaces test_wo153_complete_browser.py::test_browser_many_cards_print_on_one_page_and_follow_a_change (wording only, #187).
def test_browser_many_cards_print_on_one_page_and_follow_a_change(
    page: Page, live_folders: str, tmp_path: Path
) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 1440)
    page.get_by_role("button", name=section_copy("case")["save_label"]).click()
    page.wait_for_url("**/f/*")
    folder = page.url.rsplit("/", 1)[-1].partition("?")[0]
    db = store.FolderStore(tmp_path / "know-your-district/folders.db", state(preview=True))
    fill_with_matches(db, folder)
    page.reload(timeout=60_000)  # 25 full cards, each read fresh
    mark_document(page)
    printed = printed_rows(page)
    assert [identity(row) for row in printed] == MATCHED_ROWS

    # A saved match card changes; its own row follows without a reload.
    snap_match = page.locator(".folder-card").nth(3)  # the SNAP match in House 1
    snap_match.get_by_role("combobox", name="Status").select_option(label="Contacted")
    page.locator("#folder-print", has_text="Contacted · High priority").wait_for()
    changed = [row for row in printed_rows(page) if "Contacted" in row]
    assert [identity(row) for row in changed] == [(SNAP_MATCH, 1)]
    assert same_document(page)

    page.emulate_media(media="print")
    shown = page.locator("#folder-print").inner_text()
    assert SNAP_MATCH in shown and ABLE in shown and PRE_K in shown
    assert WORDS["print_cards"].format(shown=12, total=25, omitted=13) in shown
    assert WORDS["print_notes_omitted"].format(total=25) in shown
    assert WORDS["print_shortened"].format(count=12) in shown
    assert pdf_pages(page) == 1
    assert axe_problems(page) == []
