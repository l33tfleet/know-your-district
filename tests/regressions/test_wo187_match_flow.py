"""WO187: saving matches, with the plain folder wording.

Each test here is a copy of a superseded test in test_wo153_match_flow.py, changed only where it pinned
the old words ("Priority: X. Status: Y." is now "Priority is X. Status is Y."; the note
hint and confirmation now say "groups of people, not one resident"). Every check of
behaviour, storage, isolation, focus and accessibility is kept as it was.
"""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.folders import service, store
from app.folders.notes import date_label
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo149_matches import matching_store
from tests.regressions.test_wo150_prek import complete_store
from tests.regressions.test_wo153_match_flow import (
    BRIEF,
    EMPTY,
    FORM,
    HTMX,
    MATCH_SURFACES,
    NOTE,
    SAVE,
    SURFACES,
    VALID_CASE,
    VALID_MATCH,
    WORDS,
    card_number,
    confirmed,
    count,
    first_save,
    folder_cards,
    policy,
    save_forms,
    selection,
    site,
    submit,
    summary,
    tight,
)

__all__ = [
    "BRIEF",
    "EMPTY",
    "FORM",
    "HTMX",
    "MATCH_SURFACES",
    "NOTE",
    "SAVE",
    "SURFACES",
    "VALID_CASE",
    "VALID_MATCH",
    "WORDS",
    "axe_problems",
    "base_url",
    "browser",
    "card_number",
    "complete_store",
    "confirmed",
    "count",
    "first_save",
    "folder_cards",
    "matching_store",
    "open_page",
    "page",
    "parse",
    "policy",
    "save_forms",
    "selection",
    "site",
    "submit",
    "summary",
    "tight",
]


# Replaces test_wo153_match_flow.py::test_save_reopen_track_and_add_to_an_existing_folder (wording only, #187).
@pytest.mark.parametrize("name", SURFACES)
def test_save_reopen_track_and_add_to_an_existing_folder(
    site: TestClient, policy: Path, name: str
) -> None:
    form = first_save(site, policy, name)
    chosen = selection(form)

    created = submit(site, form)
    assert created.status_code == 303
    path = created.headers["location"]
    (card,) = folder_cards(site, path)
    number = card_number(card)
    if name in MATCH_SURFACES:
        shown = card.one("article", data_match=chosen)
        citation = shown.find_all("p", class_="case-citation")[0].text
        assert "Synthetic Census fixture" in citation and "2020–2024" in citation
        assert "agency decides eligibility" in shown.text
        assert "90% margin of error" in shown.text
    else:
        assert card.one("section", class_="case")
    attention = parse(site.get(path).text).one("section", class_="folder-attention")
    link = attention.one("a", href=f"#card-{number}")
    assert link.text.split(" · ")[0].strip()
    assert "Hawaiʻi State House District 22" in link.text

    status = site.post(f"{path}/cards/{number}/status", content="status=planned", headers=HTMX)
    assert status.status_code == 200
    live = parse(status.text).one("div", id=f"live-{number}")
    assert live.attrs["role"] == "status"
    assert live.text == "Priority is Normal. Status is Planned."
    priority = site.post(
        f"{path}/cards/{number}/priority", content="priority=high&reason=Ask+DHS", headers=HTMX
    )
    assert parse(priority.text).one("p", id=f"summary-{number}").text == (
        "Priority is High (Ask DHS). Status is Planned."
    )

    added = confirmed(site, f"{path}/cards/{number}/notes", NOTE)
    assert added.status_code == 200
    today = date_label(datetime.now(UTC).date().isoformat())
    notes = parse(added.text).one("section", id=f"notes-{number}")
    assert today in notes.one("time").text and NOTE in notes.text
    note = int(notes.one("li", class_="note").attrs["id"].removeprefix("note-"))
    edited = confirmed(site, f"{path}/notes/{note}", "Follow up with DHS outreach in May.")
    assert "Follow up with DHS outreach in May." in edited.text and NOTE not in edited.text

    reopened = parse(site.get(path).text)
    assert reopened.one("p", id=f"summary-{number}").text == (
        "Priority is High (Ask DHS). Status is Planned."
    )
    assert today in reopened.one("li", id=f"note-{note}").text

    empty = site.post(EMPTY, content="", headers=FORM).headers["location"]
    into = submit(site, form, folder=f"http://testserver{empty}")
    assert into.status_code == 303
    (saved,) = folder_cards(site, empty)
    assert into.headers["location"] == f"{empty}#card-{card_number(saved)}"
    if name in MATCH_SURFACES:
        assert saved.one("article", data_match=chosen)
    site.post(
        f"{empty}/cards/{card_number(saved)}/status", content="status=contacted", headers=FORM
    )
    again = submit(site, form, folder=empty.removeprefix("/f/"))
    assert again.headers["location"] == f"{empty}#card-{card_number(saved)}"
    assert len(folder_cards(site, empty)) == 1
    assert summary(site, empty, card_number(saved)) == "Priority is Normal. Status is Contacted."
    assert len(folder_cards(site, path)) == 1


# Replaces test_wo153_match_flow.py::test_a_match_the_tool_no_longer_offers_shows_no_figure_and_keeps_its_state (wording only, #187).
def test_a_match_the_tool_no_longer_offers_shows_no_figure_and_keeps_its_state(
    site: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.matches import DistrictMatches, ProgramMatch
    from etl.programs.mappings import ProgramMapping

    def withdrawn(
        self: DistrictMatches, mappings: tuple[ProgramMapping, ...] | None = None
    ) -> tuple[ProgramMatch, ...]:
        return ()

    path = site.post(EMPTY, content=VALID_MATCH, headers=FORM).headers["location"]
    number = card_number(folder_cards(site, path)[0])
    site.post(f"{path}/cards/{number}/status", content="status=planned", headers=FORM)
    monkeypatch.setattr(DistrictMatches, "get_matches", withdrawn)
    (card,) = folder_cards(site, path)
    assert WORDS["match_gone"] in card.text
    assert not card.find_all("article")
    assert summary(site, path, number) == "Priority is Normal. Status is Planned."


# Replaces test_wo153_match_flow.py::test_cards_and_notes_of_one_folder_cannot_be_changed_through_another (wording only, #187).
def test_cards_and_notes_of_one_folder_cannot_be_changed_through_another(
    site: TestClient, tmp_path: Path
) -> None:
    first = site.post(EMPTY, content=VALID_MATCH, headers=FORM).headers["location"]
    other = site.post(EMPTY, content="", headers=FORM).headers["location"]
    (card,) = folder_cards(site, first)
    number = card_number(card)
    confirmed(site, f"{first}/cards/{number}/notes", NOTE)
    note = int(parse(site.get(first).text).one("li", class_="note").attrs["id"][5:])
    for endpoint, body in (
        (f"{other}/cards/{number}/status", "status=done"),
        (f"{other}/cards/{number}/priority", "priority=low"),
        (f"{other}/cards/{number}/notes", "body=Changed"),
        (f"{other}/notes/{note}", "body=Changed"),
        (f"{other}/notes/{note}/delete", ""),
    ):
        assert site.post(endpoint, content=body, headers=FORM).status_code == 404, endpoint
    assert summary(site, first, number) == "Priority is Normal. Status is Idea."
    assert NOTE in parse(site.get(first).text).one("li", id=f"note-{note}").text
    assert folder_cards(site, other) == []


# Replaces test_wo153_match_flow.py::test_every_existing_folder_write_is_throttled (wording only, #187).
@pytest.mark.parametrize("write", ["status", "priority", "match", "case", "cases_route"])
def test_every_existing_folder_write_is_throttled(
    site: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str
) -> None:
    path = site.post(EMPTY, content=VALID_MATCH, headers=FORM).headers["location"]
    number = card_number(folder_cards(site, path)[0])
    tight(monkeypatch, "WRITE_PER_IP")
    first = site.post(f"{path}/cards/{number}/status", content="status=planned", headers=FORM)
    assert first.status_code == 303
    folder = path.removeprefix("/f/")
    endpoint, body = {
        "status": (f"{path}/cards/{number}/status", "status=done"),
        "priority": (f"{path}/cards/{number}/priority", "priority=low"),
        "match": (EMPTY, f"population_id=disability&program_id=hawaii-able&folder={folder}"),
        "case": ("/folders", f"{VALID_CASE}&folder={folder}"),
        "cases_route": (f"{path}/cases", VALID_CASE),
    }[write]
    refused = site.post(endpoint, content=body, headers=FORM)
    assert refused.status_code == 429
    assert "Try again in" in refused.json()["detail"]
    assert summary(site, path, number) == "Priority is Normal. Status is Planned."
    assert count(tmp_path, "cards") == 1


# Replaces test_wo153_match_flow.py::test_without_a_secret_saves_still_work_and_are_still_throttled (wording only, #187).
def test_without_a_secret_saves_still_work_and_are_still_throttled(
    site: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story step 5 ran without `KYD_FOLDERS_SECRET` before saves were throttled; it still must.

    Throttling then keys its counts per process; notes still need the real secret.
    """
    monkeypatch.delenv(service.SECRET_ENV)
    for endpoint, body in ((EMPTY, ""), (EMPTY, VALID_MATCH), ("/folders", VALID_CASE)):
        saved = site.post(endpoint, content=body, headers=FORM)
        assert saved.status_code == 303, (endpoint, saved.text)
    assert (count(tmp_path, "folders"), count(tmp_path, "cards")) == (3, 2)
    path = site.post("/folders", content=VALID_CASE, headers=FORM).headers["location"]
    number = card_number(folder_cards(site, path)[0])
    for field, value in (("priority", "high"), ("status", "planned")):
        changed = site.post(
            f"{path}/cards/{number}/{field}", content=f"{field}={value}", headers=HTMX
        )
        assert changed.status_code == 200, changed.text
    assert summary(site, path, number) == "Priority is High. Status is Planned."
    note = site.post(
        f"{path}/cards/{number}/notes", content=urlencode({"body": NOTE}), headers=HTMX
    )
    assert note.status_code == 503
    assert service.SECRET_ENV in note.json()["detail"]
    assert count(tmp_path, "notes") == 0
    # The priority and status changes above already count: a limit of 3 leaves one more.
    rule: store.RateRule = service.WRITE_PER_IP
    monkeypatch.setattr(service, "WRITE_PER_IP", rule.model_copy(update={"limit": 3}))
    first = site.post(f"{path}/cards/{number}/status", content="status=done", headers=FORM)
    assert first.status_code == 303
    refused = site.post(f"{path}/cards/{number}/status", content="status=idea", headers=FORM)
    assert refused.status_code == 429
    assert summary(site, path, number) == "Priority is High. Status is Done."
    tight(monkeypatch, "CREATE_PER_IP")
    site.post(EMPTY, content="", headers=FORM)
    assert site.post(EMPTY, content="", headers=FORM).status_code == 429


# Replaces test_wo153_match_flow.py::test_story_step_5_saves_from_the_snap_region_without_a_secret (wording only, #187).
def test_story_step_5_saves_from_the_snap_region_without_a_secret(
    site: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The story server runs without `KYD_FOLDERS_SECRET`: the SNAP save must still land."""
    monkeypatch.delenv(service.SECRET_ENV)
    region = parse(site.get(BRIEF).text).one("section", aria_label="SNAP")
    (form,) = save_forms(region)
    saved = submit(site, form)
    assert saved.status_code == 303, saved.text
    page = site.get(saved.headers["location"])
    assert page.status_code == 200
    number = card_number(folder_cards(site, saved.headers["location"])[0])
    path = saved.headers["location"]
    for field, value in (("priority", "high"), ("status", "planned")):
        changed = site.post(
            f"{path}/cards/{number}/{field}", content=f"{field}={value}", headers=HTMX
        )
        assert changed.status_code == 200, changed.text
        assert "Saved" in changed.text
    assert summary(site, path, number) == "Priority is High. Status is Planned."


# Replaces test_wo153_match_flow.py::test_browser_saves_a_ranked_match_and_tracks_it_with_htmx (wording only, #187).
def test_browser_saves_a_ranked_match_and_tracks_it_with_htmx(
    page: Page, base_url: str, policy: Path
) -> None:
    open_page(page, f"{base_url}{BRIEF}", 1440)
    ranked = page.locator("section.matches")
    ranked.get_by_role("button", name=SAVE["label"]).first.click()
    page.wait_for_url("**/f/*")
    assert page.locator(".folder-card article.case").count() == 1
    assert axe_problems(page) == []
    url = page.url
    page.get_by_role("combobox", name="Status").select_option(label="Contacted")
    page.get_by_role("status").filter(has_text="Status is Contacted.").wait_for()
    assert page.url == url
    page.get_by_role("textbox", name="Add a note").fill("Asked DHS about outreach dates.")
    page.get_by_role("button", name="Add note").click()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.reload()
    assert "Status is Contacted." in page.inner_text(".folder-summary")
    assert page.locator(".note-body").inner_text() == "Asked DHS about outreach dates."
