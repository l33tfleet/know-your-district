"""#398, step 4 of #153: the retention notice and the one-page printed summary of a folder.

A folder is deleted `RETENTION` after its last saved change (`app/folders/retention.py`), and the
page says so in words taken from that value. The printout is a bounded summary, never every full
card: at most `PRINT_ROWS` cards, each reason shortened to `PRINT_REASON` characters, no note's
words and no figure. What it leaves out (cards, notes, shortened reasons) is counted on the page.
Every successful write answers with the summary and the notice out of band, so htmx 2.0 refreshes
both without reloading the page; a check step or a refusal writes nothing and refreshes nothing.
"""

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.copy import load_copy, section_copy
from app.folders import retention, store
from app.folders import routes as folder_routes
from app.folders.notes import date_label
from app.folders.references import (
    encode_match,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
)
from app.tools.matches import MatchReference
from etl.boundaries import DistrictId
from tests.regressions.test_journey_folder_notes import (
    add_in_browser,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    check,
    save,
    token_in,
)
from tests.regressions.test_journey_folder_save import (
    FORM,
    HTMX,
    Flag,
    card_id,
    client,
    create,
    flag,
    folder_store,
    live_folders,
    post,
    state,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
)
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import (
    axe_problems,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    base_url,
    browser,
    open_page,
)
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import (
    config,
    pdf_pages,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    shipped_facts,
)

# Reuse the #288 and WO122 fixtures unchanged.
__all__ = ["base_url", "browser", "client", "config", "flag", "live_folders", "page"]
__all__ += ["shipped_facts"]

CASE = "snap_no_receipt"
BRIEF = "/brief/house/22"
WORDS = load_copy()["folders"]
HAWAII = timezone(timedelta(hours=-10))
LONG_REASON = ("Outreach at the Kalihi community center " * 6)[:200].rstrip() + "s"
UNBROKEN_REASON = "x" * 200
PHONE = "Call 808-555-0142 about the next session."
# The published match labels, as `card_names` reads them; the SNAP one is the longest shipped.
ABLE = "Hawaiʻi ABLE savings program · People with a disability"
PRE_K = "EOEL Public Pre-K · Children under 5"
SNAP_MATCH = (
    "Supplemental Nutrition Assistance Program (SNAP) · Households below poverty reporting no SNAP"
)


def match(population: str, program: str, district: int) -> MatchReference:
    return MatchReference(
        district=DistrictId(chamber="house", district=district),
        population_id=population,
        program_id=program,
    )


def fill_with_matches(db: store.FolderStore, folder: str) -> None:
    """House 22's legacy case is saved already; add ABLE and Pre-K in House 1, then the SNAP
    match in Houses 1-22: 25 cards, all high priority with maximum-length reasons and a note."""
    db.save_match(folder, match("disability", "hawaii-able", 1))
    db.save_match(folder, match("children_under_5", "public-pre-k", 1))
    for district in range(1, 23):
        db.save_match(folder, match("below_poverty_no_snap", "snap", district))
    cards = db.get_folder(folder).cards
    assert len(cards) == 25
    for number, card in enumerate(cards):
        db.set_priority(folder, card.id, "high", UNBROKEN_REASON if number % 2 else LONG_REASON)
        db.add_note(folder, card.id, "n" * 1000, True)


# What the matched summary lists, in order: the legacy card, ABLE, Pre-K, then the SNAP match
# in Houses 1-9; the SNAP match in Houses 10-22 is counted as not printed.
MATCHED_ROWS = [("SNAP", 22), (ABLE, 1), (PRE_K, 1)] + [(SNAP_MATCH, d) for d in range(1, 10)]


def summary(html: str) -> Node:
    return parse(html).one("section", id="folder-print")


def rows(html: str) -> list[str]:
    return [row.text for row in summary(html).find_all("li", class_="folder-print-row")]


def disclosures(html: str) -> list[str]:
    return [line.text for line in summary(html).find_all("p", class_="folder-omitted")]


def retention_text(html: str) -> str:
    return parse(html).one("p", id="folder-retention").text


def rule(days: int) -> str:
    return WORDS["retention"].format(days=days)


def saved_line(moment: datetime) -> str:
    until = (moment + retention.RETENTION).astimezone(HAWAII).date()
    return WORDS["retention_saved"].format(
        saved=date_label(moment.astimezone(HAWAII).date().isoformat()),
        until=date_label(until.isoformat()),
    )


def oob(html: str, element_id: str) -> Node:
    found = [n for n in parse(html).find_all(id=element_id) if n.attrs.get("hx-swap-oob")]
    assert len(found) == 1, (element_id, html[:500])
    assert found[0].attrs["hx-swap-oob"] == "true"
    return found[0]


def has_oob(html: str) -> bool:
    return "hx-swap-oob" in html


# --- the retention notice ---


def test_the_folder_states_its_retention_from_the_store_rule(client: TestClient) -> None:
    html = client.get(create(client)).text
    assert timedelta(days=180) == retention.RETENTION
    assert retention_text(html) == rule(180)
    assert "180 days after its last saved change" in retention_text(html)


def test_the_notice_follows_a_changed_retention(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = create(client)
    monkeypatch.setattr(retention, "RETENTION", timedelta(days=30))
    assert retention_text(client.get(path).text) == rule(30)


def test_a_saved_change_dates_the_notice_from_the_last_write(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    before = datetime.now(UTC)
    response = post(client, f"{path}/cards/{card}/status", "status=planned", HTMX)
    after = datetime.now(UTC)
    assert response.status_code == 200
    text = oob(response.text, "folder-retention").text
    assert text.startswith(rule(180))
    assert saved_line(before) in text or saved_line(after) in text
    # Opening the folder is not a write, so a reload states the rule alone.
    assert retention_text(client.get(path).text) == rule(180)


# --- the summary, refreshed out of band by every write ---


def test_a_priority_write_refreshes_the_summary_with_its_reason(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    body = urlencode({"priority": "high", "reason": "Office outreach week"})
    response = post(client, f"{path}/cards/{card}/priority", body, HTMX)
    assert "Idea · High priority · Office outreach week" in oob(response.text, "folder-print").text


def test_note_writes_refresh_the_summary_but_checks_and_refusals_do_not(
    client: TestClient,
) -> None:
    path = create(client)
    endpoint = f"{path}/cards/{card_id(client, path)}/notes"
    checked = check(client, endpoint, "Tabled at the market.", HTMX)
    assert checked.status_code == 200 and token_in(checked.text) is not None
    assert not has_oob(checked.text)

    refused = check(client, endpoint, PHONE, HTMX)
    assert refused.status_code == 422
    assert not has_oob(refused.text)

    saved = save(client, endpoint, "Tabled at the market.", HTMX)
    today = date_label(datetime.now(UTC).date().isoformat())
    assert WORDS["print_notes"].format(count=1, dated=today) in oob(saved.text, "folder-print").text
    assert saved_line(datetime.now(UTC)) in oob(saved.text, "folder-retention").text
    # The note's words stay on the screen only: never in the printed summary.
    assert "Tabled at the market." not in oob(saved.text, "folder-print").text

    note = re.search(r'id="note-(\d+)"', client.get(path).text)
    assert note is not None
    deleted = post(client, f"{path}/notes/{note[1]}/delete", "", HTMX)
    assert WORDS["print_no_notes"] in oob(deleted.text, "folder-print").text


def test_a_plain_form_write_still_redirects_without_a_partial(client: TestClient) -> None:
    path = create(client)
    response = post(client, f"{path}/cards/{card_id(client, path)}/status", "status=done", FORM)
    assert response.status_code == 303
    assert "Done · Normal priority" in " ".join(rows(client.get(path).text))


# --- the bound and its disclosures ---


@pytest.fixture
def crowded(flag: Flag, tmp_path: Path) -> tuple[TestClient, str]:
    """25 saved cards with maximum-length reasons; the last card saved is the one high one."""
    http = flag("on")
    db = folder_store(tmp_path / "folders.db")
    folder = db.create_folder("Office", CASE, "house", 1)
    for district in range(2, 26):
        db.save_case(folder, CASE, "house", district)
    cards = db.get_folder(folder).cards
    assert len(cards) == 25
    for card in cards[:-1]:
        db.set_priority(folder, card.id, "normal", LONG_REASON)
    db.set_priority(folder, cards[-1].id, "high", UNBROKEN_REASON)
    db.set_status(folder, cards[0].id, "done")
    for card in cards[:3]:
        db.add_note(folder, card.id, "n" * 1000, True)
    db.add_note(folder, cards[-1].id, "Tabled at the market.", True)
    return http, f"/f/{folder}"


@pytest.fixture
def matched(flag: Flag, tmp_path: Path) -> tuple[TestClient, str, store.FolderStore]:
    """A legacy card and 24 saved matches, each with a maximum-length reason and a note."""
    http = flag("on")
    db = folder_store(tmp_path / "folders.db")
    folder = db.create_folder("Office", CASE, "house", 22)
    fill_with_matches(db, folder)
    return http, f"/f/{folder}", db


def identity(row: str) -> tuple[str, int]:
    found = re.search(r"Hawaiʻi State House District (\d+)", row)
    assert found is not None, row
    name = next(n for n in (SNAP_MATCH, ABLE, PRE_K, "SNAP") if row.startswith(n))
    return name, int(found[1])


def test_the_summary_lists_at_most_the_bound_and_counts_what_it_leaves_out(
    crowded: tuple[TestClient, str],
) -> None:
    http, path = crowded
    html = http.get(path).text
    assert folder_routes.PRINT_ROWS == 12
    listed = rows(html)
    assert len(listed) == 12
    assert disclosures(html) == [
        WORDS["print_cards"].format(shown=12, total=25, omitted=13),
        WORDS["print_notes_omitted"].format(total=4),
        WORDS["print_shortened"].format(count=12),
    ]
    # Every full card stays on the screen.
    assert html.count('class="folder-card"') == 25


def test_the_summary_lists_high_priority_first_and_done_last(
    crowded: tuple[TestClient, str],
) -> None:
    http, path = crowded
    listed = rows(http.get(path).text)
    assert "Hawaiʻi State House District 25" in listed[0]
    assert "High priority" in listed[0]
    # District 1 is the one done card: it sorts last, past the bound.
    assert not any(re.search(r"District 1\b", row) for row in listed)


def test_a_maximum_length_reason_is_shortened_and_marked(crowded: tuple[TestClient, str]) -> None:
    http, path = crowded
    html = http.get(path).text
    reasons = [r.text for r in summary(html).find_all("span", class_="folder-print-reason")]
    assert len(reasons) == 12
    assert all(r.endswith("…") and len(r) <= folder_routes.PRINT_REASON for r in reasons)
    assert LONG_REASON not in summary(html).text and UNBROKEN_REASON not in summary(html).text
    assert LONG_REASON in html  # the full card keeps it


def test_a_short_reason_is_not_counted_as_shortened(client: TestClient) -> None:
    path = create(client)
    post(client, f"{path}/cards/{card_id(client, path)}/priority", "priority=low&reason=Kept")
    html = client.get(path).text
    assert disclosures(html) == [
        WORDS["print_cards"].format(shown=1, total=1, omitted=0),
        WORDS["print_notes_none"],
        WORDS["print_shortened"].format(count=0),
    ]
    assert "Kept" in rows(html)[0] and "…" not in rows(html)[0]


def test_the_summary_carries_no_figure_and_no_note_words(crowded: tuple[TestClient, str]) -> None:
    http, path = crowded
    printed = summary(http.get(path).text)
    assert not printed.find_all(class_="case") and not printed.find_all(class_="figure")
    assert "Tabled at the market." not in printed.text and "n" * 50 not in printed.text


def test_the_print_rules_keep_only_the_summary() -> None:
    css = (Path(__file__).resolve().parents[2] / "static/folders.css").read_text(encoding="utf-8")
    block = re.search(r"@media print \{(.*)\}\s*$", css, flags=re.S)
    assert block is not None
    for hidden in (".folder-full", ".folder-attention", ".folder-link", ".folder-reopen"):
        assert hidden in block[1]


# --- in a real browser ---


def mark_document(page: Page) -> None:
    page.evaluate("window.kydSameDocument = true")


def same_document(page: Page) -> bool:
    return bool(page.evaluate("window.kydSameDocument === true"))


def printed_rows(page: Page) -> list[str]:
    return [" ".join(t.split()) for t in page.locator("#folder-print li").all_inner_texts()]


def test_browser_keyboard_alone_changes_status_and_the_summary_follows(
    page: Page, live_folders: str
) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 390)
    page.get_by_role("button", name=section_copy("case")["save_label"]).focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/f/*")
    mark_document(page)
    page.focus("select[name=status]")
    page.keyboard.press("ArrowDown")
    page.locator("#folder-print", has_text="Contacted · Normal priority").wait_for()
    assert page.evaluate("document.activeElement.name") == "status"
    assert same_document(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
