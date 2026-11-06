"""#289 (journey step 3): dated outreach notes on a saved case, newest first.

A note is office text about outreach and populations, at most 1,000 characters. A phone number,
email address or street address is always refused and must be removed; no confirmation lifts
that. Clean text first gets a confirm step whose token covers the exact words, and only then
saves. Delete needs no confirmation. Every write goes through `app/folders/store.py`, only while
the `folders` flag is on.
"""

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from pydantic import ValidationError

from app.copy import load_copy, section_copy
from app.folders import routes as folder_routes
from app.folders import service, store
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
)
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo_step5_save_priority import live_shipped

# Reuse the #288, #316 and WO122 fixtures unchanged.
__all__ = ["base_url", "browser", "client", "config", "flag", "live_folders", "page"]
__all__ += ["live_shipped", "shipped_facts"]

ROOT = Path(__file__).resolve().parents[2]
BRIEF = "/brief/house/22"
SECRET = "s" * 32
HINT = "Notes are about outreach and populations, not individual residents."
CONFIRM = "This note is about outreach and populations, not individual residents."
PERSONAL = "Personal phone numbers, emails and addresses are not kept here. Remove them to save."
NOTE = "Tabled at the Kalihi farmers market; families asked about SNAP."
WORDS = load_copy()["folders"]
SAMPLES = {
    "phone": "Call 808-555-0142 about the next session.",
    "email": "Write to aunty.lee@example.com before Friday.",
    "address": "Met at 1234 Kalihi Street after the meeting.",
}


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYD_FOLDERS_SECRET", SECRET)


def rows(path: Path, query: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return [tuple(row) for row in connection.execute(query)]


def live_bodies(tmp_path: Path) -> list[str]:
    return [
        r[0]
        for r in rows(tmp_path / "folders.db", "SELECT body FROM notes WHERE deleted_at IS NULL")
    ]


def all_bodies(tmp_path: Path) -> list[str]:
    if not (tmp_path / "folders.db").exists():
        return []
    return [r[0] for r in rows(tmp_path / "folders.db", "SELECT body FROM notes")]


def token_in(html: str) -> str | None:
    found = re.search(r'name="confirmation" value="([0-9a-f]+)"', html)
    return found[1] if found else None


def check(client: TestClient, endpoint: str, body: str, headers: dict[str, str] = FORM) -> Any:
    return post(client, endpoint, urlencode({"body": body}), headers)


def save(client: TestClient, endpoint: str, body: str, headers: dict[str, str] = FORM) -> Any:
    """The two steps an office takes: check the words, then confirm them."""
    checked = check(client, endpoint, body, headers)
    assert checked.status_code == 200, checked.text
    token = token_in(checked.text)
    assert token is not None
    return post(client, endpoint, urlencode({"body": body, "confirmation": token}), headers)


def notes_endpoint(client: TestClient, path: str) -> str:
    return f"{path}/cards/{card_id(client, path)}/notes"


def note_ids(client: TestClient, path: str) -> list[int]:
    return [int(i) for i in re.findall(r'id="note-(\d+)"', client.get(path).text)]


def shown(client: TestClient, path: str) -> list[str]:
    document = parse(client.get(path).text)
    return [" ".join(p.text.split()) for p in document.find_all("p", class_="note-body")]


@pytest.fixture
def folder(client: TestClient) -> str:
    return create(client)


# --- the flag: every folder route, the note routes included ---


def routes(folder: str, card: int = 1, note: int = 1) -> list[tuple[str, str, str]]:
    save_body = "case_id=snap_no_receipt&chamber=house&district=22"
    return [
        ("POST", "/folders", save_body),
        ("GET", f"/f/{folder}", ""),
        ("POST", f"/f/{folder}/cases", save_body),
        ("POST", f"/f/{folder}/cards/{card}/priority", "priority=high&reason=x"),
        ("POST", f"/f/{folder}/cards/{card}/status", "status=done"),
        ("POST", f"/f/{folder}/cards/{card}/notes", "body=x"),
        ("POST", f"/f/{folder}/notes/{note}", "body=x"),
        ("POST", f"/f/{folder}/notes/{note}/delete", ""),
    ]


def test_every_folder_route_including_the_note_routes_is_in_the_off_list() -> None:
    """Replaces #288's count test: a route added later must join `routes` by its path."""
    paths = [getattr(r, "path", "") for r in folder_routes.router.routes]
    assert len(paths) == len(set(paths)) == len(routes("x"))
    assert set(paths) == {
        "/folders",
        "/f/{folder_id}",
        "/f/{folder_id}/cases",
        "/f/{folder_id}/cards/{card_id}/priority",
        "/f/{folder_id}/cards/{card_id}/status",
        "/f/{folder_id}/cards/{card_id}/notes",
        "/f/{folder_id}/notes/{note_id}",
        "/f/{folder_id}/notes/{note_id}/delete",
    }


@pytest.mark.parametrize("status", ["off", "preview"])
def test_flag_off_every_folder_route_404s_with_html_and_writes_nothing(
    flag: Flag, tmp_path: Path, status: str
) -> None:
    client = flag("on")
    path = create(client)
    endpoint = notes_endpoint(client, path)
    assert save(client, endpoint, NOTE).status_code == 303
    note = note_ids(client, path)[0]
    before = rows(tmp_path / "folders.db", "SELECT * FROM notes")
    client = flag(status)
    for method, route, body in routes(path.removeprefix("/f/"), card_id_of(tmp_path), note):
        response = client.request(method, route, content=body, headers=FORM)
        assert response.status_code == 404, route
        assert "text/html" in response.headers["content-type"], route
    assert rows(tmp_path / "folders.db", "SELECT * FROM notes") == before
    assert len(rows(tmp_path / "folders.db", "SELECT id FROM folders")) == 1


def card_id_of(tmp_path: Path) -> int:
    return int(rows(tmp_path / "folders.db", "SELECT id FROM cards")[0][0])


@pytest.mark.parametrize("status", ["off", "preview"])
def test_flag_off_creates_no_file_on_any_route(flag: Flag, tmp_path: Path, status: str) -> None:
    client = flag(status)
    for method, route, body in routes("0" * 32):
        response = client.request(method, route, content=body, headers=FORM)
        assert response.status_code == 404, route
        assert "text/html" in response.headers["content-type"], route
    assert not (tmp_path / "folders.db").exists()


def test_flag_off_blocks_delete_in_the_store(flag: Flag, tmp_path: Path) -> None:
    flag("on")
    db = folder_store(tmp_path / "folders.db")
    folder_id = db.create_folder("One", "snap_no_receipt", "house", 22)
    card = db.get_folder(folder_id).cards[0].id
    note = db.add_note(folder_id, card, NOTE, True)
    flag("off")
    with pytest.raises(store.FoldersDisabledError):
        db.delete_note(folder_id, note)
    flag("on")
    assert [n.body for n in db.list_notes(folder_id)] == [NOTE]


# --- the confirm step ---


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


@pytest.mark.parametrize(
    "token", ["0" * 64, "", "not-a-token"], ids=["forged", "empty", "malformed"]
)
def test_a_forged_confirmation_is_refused(
    client: TestClient, folder: str, tmp_path: Path, token: str
) -> None:
    endpoint = notes_endpoint(client, folder)
    response = post(client, endpoint, urlencode({"body": NOTE, "confirmation": token}))
    assert response.status_code == 422
    assert WORDS["note_unconfirmed"] in response.text
    assert all_bodies(tmp_path) == []


def test_a_confirmation_covers_only_the_words_it_was_given_for(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    endpoint = notes_endpoint(client, folder)
    token = token_in(check(client, endpoint, NOTE).text)
    assert token is not None
    changed = post(client, endpoint, urlencode({"body": NOTE + "!", "confirmation": token}))
    assert changed.status_code == 422
    other = create(client)
    moved = post(
        client, notes_endpoint(client, other), urlencode({"body": NOTE, "confirmation": token})
    )
    assert moved.status_code == 422
    assert all_bodies(tmp_path) == []


def test_line_breaks_as_a_browser_sends_them_keep_the_confirmation(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    """Forms send CRLF; the check and the save read the same words."""
    endpoint = notes_endpoint(client, folder)
    checked = check(client, endpoint, "First line\r\nSecond line")
    token = token_in(checked.text)
    assert token is not None
    body = urlencode({"body": "First line\r\nSecond line", "confirmation": token})
    assert post(client, endpoint, body).status_code == 303
    assert live_bodies(tmp_path) == ["First line\nSecond line"]
    assert "First line<br>Second line" in client.get(folder).text


# --- personal details: refused on add and on edit, never stored ---


def assert_refused_in_place(response: Any, sample: str, tmp_path: Path) -> None:
    assert response.status_code == 422
    assert PERSONAL in response.text
    assert token_in(response.text) is None
    assert CONFIRM not in response.text
    assert sample not in all_bodies(tmp_path)


def test_a_phone_number_is_refused_on_add(client: TestClient, folder: str, tmp_path: Path) -> None:
    endpoint = notes_endpoint(client, folder)
    assert_refused_in_place(check(client, endpoint, SAMPLES["phone"]), SAMPLES["phone"], tmp_path)
    forged = post(client, endpoint, urlencode({"body": SAMPLES["phone"], "confirmation": "0" * 64}))
    assert_refused_in_place(forged, SAMPLES["phone"], tmp_path)
    assert all_bodies(tmp_path) == []


def test_an_email_address_is_refused_on_add(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    endpoint = notes_endpoint(client, folder)
    assert_refused_in_place(check(client, endpoint, SAMPLES["email"]), SAMPLES["email"], tmp_path)
    forged = post(client, endpoint, urlencode({"body": SAMPLES["email"], "confirmation": "0" * 64}))
    assert_refused_in_place(forged, SAMPLES["email"], tmp_path)
    assert all_bodies(tmp_path) == []


def test_a_street_address_is_refused_on_add(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    endpoint = notes_endpoint(client, folder)
    sample = SAMPLES["address"]
    assert_refused_in_place(check(client, endpoint, sample), sample, tmp_path)
    forged = post(client, endpoint, urlencode({"body": sample, "confirmation": "0" * 64}))
    assert_refused_in_place(forged, sample, tmp_path)
    assert all_bodies(tmp_path) == []


@pytest.fixture
def saved_note(client: TestClient, folder: str) -> int:
    assert save(client, notes_endpoint(client, folder), NOTE).status_code == 303
    return note_ids(client, folder)[0]


def assert_edit_refused(
    client: TestClient, folder: str, note: int, sample: str, tmp_path: Path
) -> None:
    endpoint = f"{folder}/notes/{note}"
    assert_refused_in_place(check(client, endpoint, sample), sample, tmp_path)
    forged = post(client, endpoint, urlencode({"body": sample, "confirmation": "0" * 64}))
    assert_refused_in_place(forged, sample, tmp_path)
    assert all_bodies(tmp_path) == [NOTE]


def test_a_phone_number_is_refused_on_edit(
    client: TestClient, folder: str, saved_note: int, tmp_path: Path
) -> None:
    assert_edit_refused(client, folder, saved_note, SAMPLES["phone"], tmp_path)


def test_an_email_address_is_refused_on_edit(
    client: TestClient, folder: str, saved_note: int, tmp_path: Path
) -> None:
    assert_edit_refused(client, folder, saved_note, SAMPLES["email"], tmp_path)


def test_a_street_address_is_refused_on_edit(
    client: TestClient, folder: str, saved_note: int, tmp_path: Path
) -> None:
    assert_edit_refused(client, folder, saved_note, SAMPLES["address"], tmp_path)


# --- plain refusals ---


def test_an_over_length_note_is_refused_with_a_plain_message(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    response = check(client, notes_endpoint(client, folder), "x" * 1001)
    assert response.status_code == 422
    text = " ".join(parse(response.text).one("p", class_="note-error").text.split())
    assert text == "A note is at most 1,000 characters; this one has 1,001. Shorten it to save."
    assert token_in(response.text) is None
    assert all_bodies(tmp_path) == []


def test_a_note_of_exactly_1000_characters_saves(
    client: TestClient, folder: str, tmp_path: Path
) -> None:
    assert save(client, notes_endpoint(client, folder), "x" * 1000).status_code == 303
    assert live_bodies(tmp_path) == ["x" * 1000]


@pytest.mark.parametrize(
    ("body", "message"),
    [("", "note_blank"), ("   \n ", "note_blank"), ("a\x07b", "note_control")],
    ids=["empty", "blank", "bell"],
)
def test_blank_and_control_character_notes_are_refused(
    client: TestClient, folder: str, tmp_path: Path, body: str, message: str
) -> None:
    response = check(client, notes_endpoint(client, folder), body)
    assert response.status_code == 422
    assert WORDS[message] in response.text
    assert all_bodies(tmp_path) == []


def test_htmx_gets_the_notes_partial_and_a_refusal_swaps_in(
    client: TestClient, folder: str
) -> None:
    endpoint = notes_endpoint(client, folder)
    card = card_id(client, folder)
    refused = check(client, endpoint, SAMPLES["phone"], HTMX)
    assert refused.status_code == 422
    assert "<html" not in refused.text
    assert f'id="notes-{card}"' in refused.text
    assert 'role="alert"' in refused.text and 'aria-invalid="true"' in refused.text
    saved = save(client, endpoint, NOTE, HTMX)
    assert saved.status_code == 200
    assert "<html" not in saved.text and NOTE in saved.text
    # The 422 still swaps: htmx 2.0 would drop it otherwise.
    assert "shouldSwap" in client.get(folder).text


def test_a_plain_form_draft_renders_the_folder_with_the_folder_link(
    client: TestClient, folder: str
) -> None:
    html = check(client, notes_endpoint(client, folder), NOTE).text
    link = parse(html).one("input", id="folder-link").attrs["value"]
    assert link == f"http://testserver{folder}"


# --- edit, delete, order ---


class Clock:
    def __init__(self, day: str) -> None:
        self.day = day

    def __call__(self) -> str:
        return f"{self.day}T09:00:00+00:00"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock("2026-10-01")
    monkeypatch.setattr(store, "now", fake)
    return fake


def test_notes_show_newest_first_with_their_dates(
    client: TestClient, folder: str, clock: Clock
) -> None:
    endpoint = notes_endpoint(client, folder)
    for day, body in (
        ("2026-10-01", "Oldest note."),
        ("2026-10-20", "Newest day, first written."),
        ("2026-10-20", "Newest day, last written."),
        ("2026-10-05", "Middle note."),
    ):
        clock.day = day
        assert save(client, endpoint, body).status_code == 303
    assert shown(client, folder) == [
        "Newest day, last written.",
        "Newest day, first written.",
        "Middle note.",
        "Oldest note.",
    ]
    times = parse(client.get(folder).text).find_all("time")
    assert [t.attrs["datetime"] for t in times] == [
        "2026-10-20",
        "2026-10-20",
        "2026-10-05",
        "2026-10-01",
    ]
    assert times[0].text.strip() == "20 October 2026"


def test_editing_keeps_the_date_and_changes_the_words(
    client: TestClient, folder: str, clock: Clock, tmp_path: Path
) -> None:
    assert save(client, notes_endpoint(client, folder), NOTE).status_code == 303
    note = note_ids(client, folder)[0]
    clock.day = "2026-10-30"
    edited = save(client, f"{folder}/notes/{note}", "Second visit planned with the food bank.")
    assert (edited.status_code, edited.headers["location"]) == (303, folder)
    assert shown(client, folder) == ["Second visit planned with the food bank."]
    assert rows(tmp_path / "folders.db", "SELECT dated FROM notes") == [("2026-10-01",)]


def test_deleting_hides_the_note_without_a_confirmation(
    client: TestClient, folder: str, saved_note: int, tmp_path: Path
) -> None:
    deleted = post(client, f"{folder}/notes/{saved_note}/delete", "")
    assert (deleted.status_code, deleted.headers["location"]) == (303, folder)
    assert shown(client, folder) == []
    assert live_bodies(tmp_path) == []
    assert rows(tmp_path / "folders.db", "SELECT deleted_at IS NOT NULL FROM notes") == [(1,)]
    again = post(client, f"{folder}/notes/{saved_note}/delete", "")
    assert again.status_code == 404


def test_another_folder_cannot_edit_or_delete_a_note(
    client: TestClient, folder: str, saved_note: int, tmp_path: Path
) -> None:
    other = create(client)
    assert check(client, f"{other}/notes/{saved_note}", "Mine now.").status_code == 404
    assert post(client, f"{other}/notes/{saved_note}/delete", "").status_code == 404
    card = card_id(client, folder)
    assert check(client, f"{other}/cards/{card}/notes", "Mine now.").status_code == 404
    assert live_bodies(tmp_path) == [NOTE]
    assert shown(client, other) == []


@pytest.mark.parametrize("note", ["0", "x", "1.5", "-1", "%C2%B2"])
def test_a_malformed_note_id_is_404(client: TestClient, folder: str, note: str) -> None:
    assert check(client, f"{folder}/notes/{note}", NOTE).status_code == 404
    assert post(client, f"{folder}/notes/{note}/delete", "").status_code == 404


def test_store_delete_is_scoped_to_its_folder(flag: Flag, tmp_path: Path) -> None:
    flag("on")
    db = folder_store(tmp_path / "folders.db")
    first = db.create_folder("One", "snap_no_receipt", "house", 22)
    second = db.create_folder("Two", "snap_no_receipt", "house", 22)
    note = db.add_note(first, db.get_folder(first).cards[0].id, NOTE, True)
    with pytest.raises(store.FolderNotFoundError):
        db.delete_note(second, note)
    with pytest.raises(ValidationError):
        db.delete_note(first, 0)
    db.delete_note(first, note)
    assert db.list_notes(first) == ()
    with pytest.raises(store.FolderNotFoundError):
        db.delete_note(first, note)


def test_a_saved_note_shows_its_words_once_until_its_editor_opens(
    client: TestClient, folder: str, saved_note: int
) -> None:
    """The Demo's `see` finds one match: the edit box loads only when asked for."""
    html = client.get(folder).text
    assert html.count(NOTE) == 1
    assert f'href="{folder}?edit={saved_note}#note-{saved_note}"' in html
    editing = parse(client.get(f"{folder}?edit={saved_note}").text)
    box = editing.one("textarea", id=f"note-{saved_note}-edit")
    assert box.text.strip() == NOTE
    assert "autofocus" in box.attrs
    link = editing.one("input", id="folder-link").attrs["value"]
    assert link == f"http://testserver{folder}"


@pytest.mark.parametrize("edit", ["0", "x", "-1"])
def test_a_malformed_editor_id_is_404(client: TestClient, folder: str, edit: str) -> None:
    assert client.get(f"{folder}?edit={edit}").status_code == 404


def test_a_note_is_escaped_on_the_page(client: TestClient, folder: str) -> None:
    assert save(client, notes_endpoint(client, folder), "<b>bold</b> outreach").status_code == 303
    html = client.get(folder).text
    assert "<b>bold</b>" not in html and "&lt;b&gt;bold&lt;/b&gt;" in html


# --- limits and settings ---


def test_too_many_writes_answer_429_with_retry_after(
    client: TestClient, folder: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        service, "WRITE_PER_IP", service.RateRule(scope="write:ip:", limit=1, window_seconds=60)
    )
    endpoint = notes_endpoint(client, folder)
    assert save(client, endpoint, NOTE).status_code == 303
    refused = save(client, endpoint, "A second note.")
    assert refused.status_code == 429
    assert 0 < int(refused.headers["retry-after"]) <= 60
    note = note_ids(client, folder)[0]
    assert post(client, f"{folder}/notes/{note}/delete", "").status_code == 429
    assert live_bodies(tmp_path) == [NOTE]


def test_without_a_secret_notes_are_503_and_the_folder_still_opens(
    client: TestClient, folder: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("KYD_FOLDERS_SECRET")
    response = check(client, notes_endpoint(client, folder), NOTE)
    assert response.status_code == 503
    assert "KYD_FOLDERS_SECRET" in response.json()["detail"]
    assert post(client, f"{folder}/notes/1/delete", "").status_code == 503
    assert client.get(folder).status_code == 200
    assert all_bodies(tmp_path) == []


# --- the box: labelled, described, bounded ---


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


# --- the privacy note names notes ---


def privacy_note() -> str:
    return " ".join((ROOT / "docs/security-privacy.md").read_text(encoding="utf-8").split())


@pytest.mark.parametrize(
    "fact",
    [
        "dated notes (at most 1,000 characters)",
        "Keep personal details out of folder names, reasons and notes",
        "notes holding contact details are always refused",
    ],
)
def test_privacy_note_states_the_note_facts(fact: str) -> None:
    assert fact in privacy_note()


# --- the browser ---


def open_folder(page: Page, base: str, width: int = 1440) -> None:
    open_page(page, f"{base}{BRIEF}?preview=1", width)
    page.get_by_role("button", name=section_copy("case")["save_label"]).click()
    page.wait_for_url("**/f/*")


def add_in_browser(page: Page, body: str) -> None:
    page.get_by_role("textbox", name="Add a note").fill(body)
    page.get_by_role("button", name="Add note").click()
    page.get_by_text(CONFIRM).wait_for()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.locator(".note-body", has_text=body).wait_for()


def browser_notes(page: Page) -> list[str]:
    return [" ".join(t.split()) for t in page.locator(".note-body").all_inner_texts()]


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


def test_browser_refuses_a_phone_number_in_place_and_keeps_focus(
    page: Page, live_folders: str
) -> None:
    open_folder(page, live_folders, 390)
    box = page.get_by_role("textbox", name="Add a note")
    box.fill(SAMPLES["phone"])
    page.get_by_role("button", name="Add note").click()
    page.get_by_role("alert").get_by_text(PERSONAL).wait_for()
    box = page.get_by_role("textbox", name="Add a note")
    assert box.get_attribute("aria-invalid") == "true"
    assert box.input_value() == SAMPLES["phone"]
    assert page.evaluate("document.activeElement.name") == "body"
    assert page.get_by_role("button", name="Save note").count() == 0
    assert axe_problems(page) == []
    page.reload()
    assert browser_notes(page) == []


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


def test_browser_story_step_6_finds_the_box_by_its_accessible_name(
    page: Page, live_folders: str
) -> None:
    open_folder(page, live_folders)
    page.get_by_role("textbox", name="Add a note").fill("Story step six note.")
    page.get_by_role("button", name="Add note").click()
    page.get_by_text("Story step six note.").wait_for()


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
    page.get_by_text("Priority: High. Status: Idea.", exact=True).wait_for()
    page.get_by_role("combobox", name="Status").select_option(label="Planned")
    page.get_by_text("Priority: High. Status: Planned.", exact=True).wait_for()

    page.get_by_role("textbox", name="Add a note").fill("Table at Mōʻiliʻili meeting 11/8")
    page.get_by_role("button", name="Add note").click()
    page.get_by_text("Table at Mōʻiliʻili meeting 11/8").first.wait_for()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.reload()
    assert browser_notes(page) == ["Table at Mōʻiliʻili meeting 11/8"]


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
