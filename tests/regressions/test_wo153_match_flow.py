"""#396 (#153 step 2): save a card from every surface, then track it in a folder.

The opening case, ranked matches, program cards, the match page and Ask (match and legacy case
answers) each offer one save form: blank folder link starts a new folder, a pasted link saves
into that folder. `POST /folders?district=house-22` with no selection starts an empty folder.
Folders keep public selection identities and office state only; a saved match re-reads its
figures through the matching tool on every render. Every write is throttled; creations spend
the creation limits; note safeguards hold on match cards as on cases.
"""

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app import features
from app.copy import load_copy, section_copy
from app.folders import service, store
from app.folders.notes import date_label
from app.main import app as asgi_app
from app.page_state import page_state
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import (
    axe_problems,
    base_url,
    browser,
    open_page,
)
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo149_matches import matching_store
from tests.regressions.test_wo150_prek import complete_store

__all__ = ["base_url", "browser", "complete_store", "matching_store", "page"]

FLAGS = 'outreach = "on"\nfolders = "on"\nmatches = "on"\nprogram_cards = "on"\nask = "on"\n'
SAVE = section_copy("folder_save")
WORDS = load_copy()["folders"]
FORM = {"content-type": "application/x-www-form-urlencoded"}
HTMX = FORM | {"HX-Request": "true"}
IP = ("192.0.2.10", 5000)
BRIEF = "/brief/house/22"
GEOGRAPHY = "house:15:022:2022"
EMPTY = "/folders?district=house-22"
SURFACES = ["opening", "ranked", "program", "detail", "ask", "ask_legacy"]
MATCH_SURFACES = {"ranked", "program", "detail", "ask"}
NOTE = "Tabled at the Kalihi farmers market; families asked about SNAP."


@pytest.fixture
def policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, complete_store: Path) -> Path:
    path = tmp_path / "features.toml"
    path.write_text(FLAGS, encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    monkeypatch.setenv("KYD_FOLDERS_DB", str(tmp_path / "folders.db"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return path


@pytest.fixture
def site(policy: Path) -> TestClient:
    return TestClient(asgi_app, follow_redirects=False, client=IP)


def count(tmp_path: Path, table: str) -> int:
    path = tmp_path / "folders.db"
    if not path.exists():
        return 0
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def surface(site: TestClient, policy: Path, name: str) -> Node:
    """The part of the page that holds the surface's cards."""
    if name == "ask_legacy":
        policy.write_text(FLAGS.replace('matches = "on"', 'matches = "off"'), encoding="utf-8")
    if name in ("ask", "ask_legacy"):
        answer = site.post(f"{BRIEF}/ask", content="choice=snap_no_receipt", headers=FORM)
        assert answer.status_code == 200, answer.text
        return parse(answer.text)
    if name == "detail":
        found = site.get("/match/house/22/public-pre-k/children_under_5")
        assert found.status_code == 200
        return parse(found.text)
    brief = parse(site.get(BRIEF).text)
    tag, cls = {"opening": ("section", "case"), "ranked": ("section", "matches")}.get(
        name, ("section", "programs")
    )
    return brief.one(tag, class_=cls)


def save_forms(node: Node) -> list[Node]:
    return [f for f in node.find_all("form") if f.attrs.get("action", "").startswith("/folders")]


def fields(form: Node, folder: str = "") -> dict[str, str]:
    hidden = {i.attrs["name"]: i.attrs["value"] for i in form.find_all("input", type="hidden")}
    return hidden | {"folder": folder}


def submit(site: TestClient, form: Node, folder: str = "") -> Any:
    return site.post(form.attrs["action"], content=urlencode(fields(form, folder)), headers=FORM)


def folder_cards(site: TestClient, path: str) -> list[Node]:
    return parse(site.get(path).text).find_all("div", class_="folder-card")


def card_number(card: Node) -> int:
    return int(card.attrs["id"].removeprefix("card-"))


def summary(site: TestClient, path: str, card: int) -> str:
    return parse(site.get(path).text).one("p", id=f"summary-{card}").text


def token_in(html: str) -> str:
    found = re.search(r'name="confirmation" value="([0-9a-f]+)"', html)
    assert found is not None, html
    return found[1]


def confirmed(site: TestClient, endpoint: str, body: str) -> Any:
    checked = site.post(endpoint, content=urlencode({"body": body}), headers=HTMX)
    assert checked.status_code == 200, checked.text
    data = urlencode({"body": body, "confirmation": token_in(checked.text)})
    return site.post(endpoint, content=data, headers=HTMX)


def selection(form: Node) -> str:
    hidden = fields(form)
    if "case_id" in hidden:
        return hidden["case_id"]
    return f"{GEOGRAPHY}:{hidden['population_id']}:{hidden['program_id']}"


def first_save(site: TestClient, policy: Path, name: str) -> Node:
    forms = save_forms(surface(site, policy, name))
    assert forms, name
    return forms[0]


# --- every surface shows the save control, and only while folders are on ---


@pytest.mark.parametrize("name", SURFACES)
def test_every_surface_offers_one_labelled_save_form_per_card(
    site: TestClient, policy: Path, name: str
) -> None:
    assert SAVE["label"].strip() and SAVE["existing"].strip()
    node = surface(site, policy, name)
    forms = save_forms(node)
    assert forms
    for form in forms:
        assert form.attrs["method"] == "post"
        assert form.one("button").text == (
            section_copy("case")["save_label"] if "case_id" in fields(form) else SAVE["label"]
        )
        field = form.one("input", name="folder")
        label = form.one("label")
        assert label.attrs["for"] == field.attrs["id"]
        assert label.text == SAVE["existing"]
    ids = [n.attrs["id"] for n in node.find_all() if "id" in n.attrs]
    assert len(ids) == len(set(ids))
    if name in MATCH_SURFACES:
        cards = node.find_all("article", class_="case")
        assert len(forms) == len(cards)
        assert {selection(f) for f in forms} == {c.attrs["data-match"] for c in cards}


def test_brief_ids_stay_unique_with_every_card_surface_on(site: TestClient) -> None:
    brief = parse(site.get(BRIEF).text)
    assert len(save_forms(brief)) >= 3
    ids = [n.attrs["id"] for n in brief.find_all() if "id" in n.attrs]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("name", SURFACES)
def test_folders_off_removes_every_save_form(site: TestClient, policy: Path, name: str) -> None:
    policy.write_text(FLAGS.replace('folders = "on"', 'folders = "off"'), encoding="utf-8")
    node = surface(site, policy, name.replace("ask_legacy", "ask"))
    if name == "ask_legacy":
        policy.write_text(
            FLAGS.replace('folders = "on"', 'folders = "off"').replace(
                'matches = "on"', 'matches = "off"'
            ),
            encoding="utf-8",
        )
        node = parse(site.post(f"{BRIEF}/ask", content="choice=snap_no_receipt", headers=FORM).text)
        assert node.find_all("section", class_="case")
    assert save_forms(node) == []
    assert site.post(EMPTY, content="", headers=FORM).status_code == 404


def test_preview_flag_carries_preview_into_every_match_form(site: TestClient, policy: Path) -> None:
    policy.write_text(FLAGS.replace('folders = "on"', 'folders = "preview"'), encoding="utf-8")
    assert save_forms(parse(site.get(BRIEF).text)) == []
    forms = save_forms(parse(site.get(f"{BRIEF}?preview=1").text))
    assert forms
    assert all(f.attrs["action"].endswith("preview=1") for f in forms)
    created = submit(site, next(f for f in forms if "population_id" in fields(f)))
    assert created.status_code == 303
    assert created.headers["location"].endswith("?preview=1")


# --- empty folders ---


def test_empty_folder_from_a_district_query(site: TestClient, tmp_path: Path) -> None:
    created = site.post(EMPTY, content="", headers=FORM)
    assert created.status_code == 303
    path = created.headers["location"]
    assert re.fullmatch(r"/f/[0-9a-f]{32}", path)
    html = site.get(path).text
    assert "Hawaiʻi State House District 22" in parse(html).one("h1").text
    assert WORDS["empty"] in html
    assert (count(tmp_path, "folders"), count(tmp_path, "cards")) == (1, 0)


# --- the journey, from each surface ---


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
    assert live.text == "Priority: Normal. Status: Planned."
    priority = site.post(
        f"{path}/cards/{number}/priority", content="priority=high&reason=Ask+DHS", headers=HTMX
    )
    assert parse(priority.text).one("p", id=f"summary-{number}").text == (
        "Priority: High (Ask DHS). Status: Planned."
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
        "Priority: High (Ask DHS). Status: Planned."
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
    assert summary(site, empty, card_number(saved)) == "Priority: Normal. Status: Contacted."
    assert len(folder_cards(site, path)) == 1


def test_ask_answer_saves_the_selected_match(site: TestClient, policy: Path) -> None:
    forms = save_forms(surface(site, policy, "ask"))
    assert {fields(f)["population_id"] for f in forms} == {"below_poverty_no_snap"}
    path = submit(site, forms[0]).headers["location"]
    (card,) = folder_cards(site, path)
    assert card.one("article", data_match=f"{GEOGRAPHY}:below_poverty_no_snap:snap")


def test_a_saved_match_is_read_afresh_and_keeps_no_figure(
    site: TestClient, policy: Path, tmp_path: Path, complete_store: Path
) -> None:
    path = submit(site, first_save(site, policy, "detail")).headers["location"]
    with closing(sqlite3.connect(tmp_path / "folders.db")) as db:
        keys = [row[0] for row in db.execute("SELECT card_key FROM cards")]
    assert keys == ["match:v1:children_under_5:public-pre-k"]
    with sqlite3.connect(complete_store) as facts:
        facts.execute("UPDATE facts SET value = 4321 WHERE variable = 'B01001_003E'")
    assert "4321" in folder_cards(site, path)[0].text


def test_a_demo_folder_save_lands_in_a_private_copy(site: TestClient, tmp_path: Path) -> None:
    state = page_state("house", "22")
    assert state is not None
    db = store.FolderStore(tmp_path / "folders.db", state)
    seed = store.DemoCard(
        case_id="snap_no_receipt", priority="high", status="planned", body=NOTE, dated="2026-11-01"
    )
    db.refresh_demo((seed,))
    form = save_forms(surface(site, Path(), "detail"))[0]
    moved = submit(site, form, folder=store.DEMO_ID)
    assert moved.status_code == 303
    copy = moved.headers["location"].partition("#")[0]
    assert copy != f"/f/{store.DEMO_ID}"
    assert len(folder_cards(site, copy)) == 2
    assert len(db.get_folder(store.DEMO_ID).cards) == 1


# --- refusals: each check alone, nothing written ---


VALID_MATCH = "population_id=children_under_5&program_id=public-pre-k"
VALID_CASE = "case_id=snap_no_receipt&chamber=house&district=22"


@pytest.mark.parametrize(
    "query,body,message",
    [
        ("?district=house-99", VALID_MATCH, "Unknown district."),
        ("?district=house22", VALID_MATCH, "Unknown district."),
        ("?district=house-22", VALID_CASE, "Give the district once"),
        ("?district=house-22", VALID_MATCH + "&value=1234", "Unknown form fields: value."),
        ("?district=house-22", VALID_MATCH + "&case_id=snap_no_receipt", "not both"),
        ("?district=house-22", "population_id=children_under_5", "needs both"),
        ("?district=house-22", "population_id=disability&program_id=snap", "Unknown match"),
        ("?district=house-22", "population_id=Bad%25&program_id=snap", "Unknown match"),
        ("", "case_id=invented&chamber=house&district=22", "Unknown case 'invented'"),
        ("?district=house-22", VALID_MATCH + "&folder=../../etc", "Unknown folder link"),
        ("?district=house-22", VALID_MATCH + f"&folder={'a' * 32}%3Fx%3D1", "Unknown folder link"),
        ("?district=house-22", f"folder={'a' * 32}", "Choose a case or a match"),
    ],
)
def test_bad_save_requests_are_refused_before_any_write(
    site: TestClient, tmp_path: Path, query: str, body: str, message: str
) -> None:
    refused = site.post(f"/folders{query}", content=body, headers=FORM)
    assert refused.status_code == 422, refused.text
    assert message in refused.json()["detail"]
    assert (count(tmp_path, "folders"), count(tmp_path, "cards")) == (0, 0)


def test_a_full_folder_refuses_the_save_and_keeps_its_cards(
    site: TestClient, tmp_path: Path
) -> None:
    state = page_state("house", "22")
    assert state is not None
    db = store.FolderStore(tmp_path / "folders.db", state)
    folder = db.create_empty_folder("Full folder")
    for number in range(200):
        db.save_case(folder, f"case_{number}", "house", 22)
    refused = site.post(EMPTY, content=f"{VALID_MATCH}&folder={folder}", headers=FORM)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "A folder can keep at most 200 cards. Nothing was saved."
    assert len(db.get_folder(folder).cards) == 200


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
    assert summary(site, path, number) == "Priority: Normal. Status: Planned."


def test_unknown_match_names_the_valid_matches(site: TestClient) -> None:
    refused = site.post(EMPTY, content="population_id=disability&program_id=snap", headers=FORM)
    assert "children_under_5 · public-pre-k" in refused.json()["detail"]


def test_an_unknown_folder_is_404_and_writes_nothing(site: TestClient, tmp_path: Path) -> None:
    empty = site.post(EMPTY, content="", headers=FORM).headers["location"]
    absent = site.post(EMPTY, content=f"{VALID_MATCH}&folder={'0' * 32}", headers=FORM)
    assert absent.status_code == 404
    assert (count(tmp_path, "folders"), count(tmp_path, "cards")) == (1, 0)
    assert folder_cards(site, empty) == []


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
    assert summary(site, first, number) == "Priority: Normal. Status: Idea."
    assert NOTE in parse(site.get(first).text).one("li", id=f"note-{note}").text
    assert folder_cards(site, other) == []


def test_note_safeguards_hold_on_a_match_card(site: TestClient, tmp_path: Path) -> None:
    path = site.post(EMPTY, content=VALID_MATCH, headers=FORM).headers["location"]
    number = card_number(folder_cards(site, path)[0])
    endpoint = f"{path}/cards/{number}/notes"
    personal = "Call 808-555-0142 about the next session."
    refused = site.post(endpoint, content=urlencode({"body": personal}), headers=HTMX)
    assert refused.status_code == 422
    assert WORDS["note_personal"] in refused.text
    forged = urlencode({"body": NOTE, "confirmation": "0" * 64})
    unconfirmed = site.post(endpoint, content=forged, headers=HTMX)
    assert WORDS["note_unconfirmed"] in unconfirmed.text
    assert count(tmp_path, "notes") == 0


# --- limits ---


def tight(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    rule: store.RateRule = getattr(service, name)
    monkeypatch.setattr(service, name, rule.model_copy(update={"limit": 1}))


@pytest.mark.parametrize("rule", ["CREATE_PER_IP", "CREATE_GLOBAL"])
@pytest.mark.parametrize("body", ["", VALID_MATCH, VALID_CASE])
def test_every_kind_of_new_folder_spends_the_creation_limits(
    site: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule: str, body: str
) -> None:
    tight(monkeypatch, rule)
    query = "" if body == VALID_CASE else "?district=house-22"
    assert site.post(f"/folders{query}", content=body, headers=FORM).status_code == 303
    another = TestClient(asgi_app, follow_redirects=False, client=("192.0.2.99", 5000))
    second = (site if rule == "CREATE_PER_IP" else another).post(
        f"/folders{query}", content=body, headers=FORM
    )
    assert second.status_code == 429
    assert second.headers["Retry-After"].isdigit()
    assert "Try again in" in second.json()["detail"]
    assert count(tmp_path, "folders") == 1


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
    assert summary(site, path, number) == "Priority: Normal. Status: Planned."
    assert count(tmp_path, "cards") == 1


def test_without_a_secret_no_folder_is_created_or_changed(
    site: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = site.post(EMPTY, content=VALID_MATCH, headers=FORM).headers["location"]
    number = card_number(folder_cards(site, path)[0])
    monkeypatch.delenv(service.SECRET_ENV)
    for endpoint, body in (
        (EMPTY, ""),
        (EMPTY, VALID_MATCH),
        ("/folders", VALID_CASE),
        (f"{path}/cards/{number}/status", "status=done"),
    ):
        refused = site.post(endpoint, content=body, headers=FORM)
        assert refused.status_code == 503, endpoint
        assert service.SECRET_ENV in refused.json()["detail"]
    assert (count(tmp_path, "folders"), count(tmp_path, "cards")) == (1, 1)
    assert summary(site, path, number) == "Priority: Normal. Status: Idea."


# --- the browser: htmx updates on a saved match card ---


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
    page.get_by_role("status").filter(has_text="Status: Contacted.").wait_for()
    assert page.url == url
    page.get_by_role("textbox", name="Add a note").fill("Asked DHS about outreach dates.")
    page.get_by_role("button", name="Add note").click()
    page.get_by_role("button", name="Save note").click()
    page.locator(".note-confirm").wait_for(state="detached")
    page.reload()
    assert "Status: Contacted." in page.inner_text(".folder-summary")
    assert page.locator(".note-body").inner_text() == "Asked DHS about outreach dates."
