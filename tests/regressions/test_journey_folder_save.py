"""#288 (journey step 2): an office saves the opening case to a folder it owns by link.

A folder keeps a case id, a district, a priority with its reason and a status, never a figure:
the page re-reads every number on each render. All writes go through `app/folders/store.py` and
only while the `folders` flag is on. Unknown ids answer 404, and nothing is written when the flag
is off.
"""

import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, get_args
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from pydantic import ValidationError

from app import features, snap
from app.copy import section_copy
from app.folders import routes as folder_routes
from app.folders import store
from app.main import app as asgi_app
from app.page_state import PageState, page_state
from etl.boundaries import DistrictId
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

# Reuse the WO122 server and Chromium fixtures unchanged.
__all__ = ["base_url", "browser", "config", "page", "shipped_facts"]

ROOT = Path(__file__).resolve().parents[2]
CASE = "snap_no_receipt"
BRIEF = "/brief/house/22"
NOTICE = "Anyone with this link can open and edit this folder"
FORM = {"content-type": "application/x-www-form-urlencoded"}
HTMX = FORM | {"HX-Request": "true"}
ABSENT = "0" * 32
LIMIT = 128 * 1024

COPY = section_copy("case")
Flag = Callable[[str], TestClient]


def state(*, preview: bool = False) -> PageState:
    result = page_state("house", "22", preview=preview)
    assert result is not None
    return result


@pytest.fixture
def flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flag:
    """Set `folders` in a private policy, with the store file outside the checkout."""

    def write(status: str) -> TestClient:
        policy = tmp_path / "features.toml"
        policy.write_text(f'outreach = "on"\nfolders = "{status}"\n', encoding="utf-8")
        monkeypatch.setattr(features, "FEATURES_PATH", policy)
        return TestClient(asgi_app, follow_redirects=False)

    monkeypatch.setenv("KYD_FOLDERS_DB", str(tmp_path / "folders.db"))
    return write


@pytest.fixture
def client(flag: Flag) -> TestClient:
    return flag("on")


def folder_store(path: Path) -> store.FolderStore:
    return store.FolderStore(path, state())


@pytest.fixture
def db(client: TestClient, tmp_path: Path) -> store.FolderStore:
    return folder_store(tmp_path / "folders.db")


def create(client: TestClient, query: str = "") -> str:
    """Save the case from the brief's control and return the folder's path."""
    body = f"case_id={CASE}&chamber=house&district=22"
    response = client.post(f"/folders{query}", content=body, headers=FORM)
    assert response.status_code == 303
    return response.headers["location"].partition("?")[0]


def card_id(client: TestClient, path: str) -> int:
    found = re.search(r'id="card-(\d+)"', client.get(path).text)
    assert found is not None
    return int(found[1])


def post(client: TestClient, path: str, body: str, headers: dict[str, str] = FORM) -> Any:
    return client.post(path, content=body, headers=headers)


def rows(path: Path, query: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return [tuple(row) for row in connection.execute(query)]


# --- the journey ---


def test_saving_shows_the_link_and_the_case_figures_come_from_the_fact_table(
    client: TestClient,
) -> None:
    html = client.get(create(client)).text
    assert NOTICE in html
    document = parse(html)
    assert document.find_all("button", class_="copy-link")
    reading = snap.load_result(DistrictId(chamber="house", district=22)).district
    shown = document.one("section", class_="case")
    assert reading.value_text in shown.text and reading.moe_text in shown.text
    assert reading.reliability_word in shown.text
    assert (reading.fact is not None) and reading.fact.table_id in shown.one(
        "p", class_="case-citation"
    ).text


def test_folder_rows_hold_no_figure(client: TestClient, tmp_path: Path) -> None:
    create(client)
    columns = {row[1] for row in rows(tmp_path / "folders.db", "PRAGMA table_info(cards)")}
    assert columns == {
        "id",
        "folder_id",
        "card_key",
        "chamber",
        "district",
        "priority",
        "reason",
        "status",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert rows(tmp_path / "folders.db", "SELECT card_key, chamber, district FROM cards") == [
        (CASE, "house", 22)
    ]


def test_a_new_figure_shows_on_the_next_render(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folder keeps no figure, so a rebuilt fact table changes the saved case."""
    path = create(client)
    published = snap.load_result(DistrictId(chamber="house", district=22)).district.value_text
    assert published in client.get(path).text

    monkeypatch.setattr(snap, "SNAP_DB", tmp_path / "absent.db")
    html = client.get(path).text
    assert published not in html
    assert "so this card shows no count" in html


def test_plain_posts_redirect_and_reloading_shows_the_same_values(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    saved = post(client, f"{path}/cards/{card}/priority", "priority=high&reason=Asked+first")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    saved = post(client, f"{path}/cards/{card}/status", "status=planned")
    assert (saved.status_code, saved.headers["location"]) == (303, path)

    document = parse(client.get(path).text)
    summary = " ".join(document.one("p", class_="folder-summary").text.split())
    assert "Priority: high" in summary and "Asked first" in summary and "Status: planned" in summary


def test_htmx_gets_the_card_partial_not_a_redirect(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    response = post(client, f"{path}/cards/{card}/status", "status=contacted", HTMX)
    assert response.status_code == 200
    assert "<html" not in response.text
    assert f'id="summary-{card}"' in response.text and "Status: contacted" in response.text


def test_controls_are_labelled_and_changes_are_announced(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    html = client.get(path).text
    for name in ("priority", "reason", "status"):
        assert f'<label for="{name}-{card}">' in html
        assert f'id="{name}-{card}"' in html
    assert parse(html).one("div", class_="folder-live").attrs["role"] == "status"
    assert 'maxlength="200"' in html
    # The swap replaces only the summary, so focus stays on the control just used.
    assert html.count(f'hx-target="#live-{card}"') == 2
    assert html.count(f'hx-select="#summary-{card}"') == 2


def test_status_and_priority_offer_exactly_the_stored_choices(client: TestClient) -> None:
    html = client.get(create(client)).text
    assert re.findall(r'<option value="(\w+)"', html) == [
        *get_args(store.Priority),
        *get_args(store.Status),
    ]
    assert get_args(store.Status) == ("idea", "contacted", "planned", "done")
    assert get_args(store.Priority) == ("high", "normal", "low")


def test_saving_a_case_twice_keeps_one_card_and_its_state(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    post(client, f"{path}/cards/{card}/status", "status=done")
    saved = post(client, f"{path}/cases", f"case_id={CASE}&chamber=house&district=22")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert client.get(path).text.count('class="folder-card"') == 1
    assert "Status: done" in client.get(path).text


def test_a_folder_holds_one_case_for_two_districts_with_valid_html(client: TestClient) -> None:
    path = create(client)
    post(client, f"{path}/cases", f"case_id={CASE}&chamber=senate&district=5")
    html = client.get(path).text
    assert html.count('class="folder-card"') == 2
    assert "Hawaiʻi State Senate District 5" in html
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_folder_links_its_evidence_to_the_brief_not_to_a_missing_anchor(
    client: TestClient,
) -> None:
    html = client.get(create(client)).text
    assert 'href="/brief/house/22#outreach-heading"' in html
    assert 'href="#outreach-heading"' not in html


def test_outreach_off_keeps_the_saved_state_and_hides_the_figures(flag: Flag) -> None:
    client = flag("on")
    path = create(client)
    policy = features.FEATURES_PATH
    policy.write_text('outreach = "off"\nfolders = "on"\n', encoding="utf-8")
    html = client.get(path).text
    assert "Status: idea" in html
    assert "B22003" not in html


# --- isolation ---


def test_a_second_folder_cannot_see_or_change_the_first(client: TestClient) -> None:
    first = create(client)
    second = create(client)
    card = card_id(client, first)
    post(client, f"{first}/cards/{card}/status", "status=planned")

    for action, body in (("status", "status=done"), ("priority", "priority=low&reason=Mine")):
        response = post(client, f"{second}/cards/{card}/{action}", body)
        assert response.status_code == 404
    assert "planned" not in client.get(second).text.split('id="live-')[1].split("</div>")[0]
    assert "Status: planned" in client.get(first).text
    assert "Mine" not in client.get(first).text


def test_store_refuses_a_card_from_another_folder(db: store.FolderStore) -> None:
    first = db.create_folder("One", CASE, "house", 22)
    second = db.create_folder("Two", CASE, "house", 22)
    card = db.get_folder(first).cards[0].id
    with pytest.raises(store.FolderNotFoundError):
        db.set_status(second, card, "done")
    with pytest.raises(store.FolderNotFoundError):
        db.set_priority(second, card, "high", "Mine")
    assert db.get_folder(first).cards[0].status == "idea"
    assert db.get_folder(first).cards[0].reason is None


def test_trashed_folder_and_card_behave_as_unknown(
    db: store.FolderStore, tmp_path: Path, client: TestClient
) -> None:
    folder = db.create_folder("One", CASE, "house", 22)
    card = db.get_folder(folder).cards[0].id
    with closing(sqlite3.connect(tmp_path / "folders.db")) as connection, connection:
        connection.execute("UPDATE cards SET deleted_at = 't'")
    assert db.get_folder(folder).cards == ()
    with pytest.raises(store.FolderNotFoundError):
        db.set_status(folder, card, "done")
    with closing(sqlite3.connect(tmp_path / "folders.db")) as connection, connection:
        connection.execute("UPDATE folders SET deleted_at = 't'")
    with pytest.raises(store.FolderNotFoundError):
        db.get_folder(folder)
    with pytest.raises(store.FolderNotFoundError):
        db.save_case(folder, CASE, "house", 22)
    assert client.get(f"/f/{folder}").status_code == 404


# --- the flag ---


def routes(folder: str, card: int = 1) -> list[tuple[str, str, str]]:
    return [
        ("POST", "/folders", f"case_id={CASE}&chamber=house&district=22"),
        ("GET", f"/f/{folder}", ""),
        ("POST", f"/f/{folder}/cases", f"case_id={CASE}&chamber=house&district=22"),
        ("POST", f"/f/{folder}/cards/{card}/priority", "priority=high&reason=x"),
        ("POST", f"/f/{folder}/cards/{card}/status", "status=done"),
    ]


def test_every_folder_route_is_covered_by_the_off_list() -> None:
    """A route added later must join `routes`, or the off test below would miss it."""
    paths = {getattr(r, "path", "") for r in folder_routes.router.routes}
    assert len(paths) == len({path for _, path, _ in routes("x")})


@pytest.mark.parametrize("status", ["off", "preview"])
def test_flag_off_removes_the_control_and_every_route_404s(
    flag: Flag, tmp_path: Path, status: str
) -> None:
    client = flag("on")
    folder = create(client).removeprefix("/f/")
    client = flag(status)
    assert "case-save" not in client.get(BRIEF).text
    for method, path, body in routes(folder):
        response = client.request(method, path, content=body, headers=FORM)
        assert response.status_code == 404, path
        assert "text/html" in response.headers["content-type"]
    assert len(rows(tmp_path / "folders.db", "SELECT id FROM folders")) == 1


def test_flag_off_is_404_before_any_input_is_read_and_makes_no_file(
    flag: Flag, tmp_path: Path
) -> None:
    client = flag("off")
    assert post(client, "/folders", "case_id=NOPE&chamber=x&district=y").status_code == 404
    assert post(client, f"/f/{ABSENT}/cards/1/status", "status=bad").status_code == 404
    assert post(client, f"/f/{ABSENT}/cards/x/status", "").status_code == 404
    assert not (tmp_path / "folders.db").exists()


def test_flag_off_blocks_the_store_itself(flag: Flag, tmp_path: Path) -> None:
    flag("on")
    db = folder_store(tmp_path / "folders.db")
    folder = db.create_folder("One", CASE, "house", 22)
    card = db.get_folder(folder).cards[0].id
    flag("off")
    for write in (
        lambda: db.create_folder("Two", CASE, "house", 22),
        lambda: db.save_case(folder, CASE, "house", 22),
        lambda: db.set_priority(folder, card, "high", "x"),
        lambda: db.set_status(folder, card, "done"),
        lambda: db.get_folder(folder),
    ):
        with pytest.raises(store.FoldersDisabledError):
            write()


def test_shipped_flag_is_preview_and_preview_carries_through_the_journey(
    flag: Flag, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = flag("preview")
    monkeypatch.setattr(features, "FEATURES_PATH", ROOT / "features.toml")
    assert features.validate_features()["folders"] == features.Status.PREVIEW
    assert "case-save" not in client.get(BRIEF).text

    html = client.get(f"{BRIEF}?preview=1").text
    assert 'action="/folders?preview=1"' in html
    body = f"case_id={CASE}&chamber=house&district=22"
    saved = post(client, "/folders?preview=1", body)
    path = saved.headers["location"]
    assert path.endswith("?preview=1")
    page_html = client.get(path).text
    bare = path.removesuffix("?preview=1")
    card = card_id(client, path)
    assert f'href="{path}"' in page_html
    for action in (f"{bare}/cards/{card}/priority", f"{bare}/cards/{card}/status"):
        assert f'hx-post="{action}?preview=1"' in page_html
        assert f'action="{action}?preview=1"' in page_html
    done = post(client, f"{bare}/cards/{card}/status?preview=1", "status=done")
    assert done.headers["location"] == path
    assert client.get(bare).status_code == 404


def test_a_malformed_preview_value_is_404(client: TestClient) -> None:
    assert client.get(f"{create(client)}?preview=2").status_code == 404


def test_save_control_is_off_the_printout() -> None:
    css = (ROOT / "static/site.css").read_text(encoding="utf-8")
    assert re.search(r"@media print \{[^@]*\.case-save\s*\{\s*display: none", css)


# --- ids and edges ---


def test_folder_ids_are_128_bit_random_hex() -> None:
    drawn = {store.new_folder_id() for _ in range(1000)}
    assert len(drawn) == 1000
    assert all(re.fullmatch(r"[0-9a-f]{32}", folder) for folder in drawn)


def test_created_folder_uses_a_drawn_id(db: store.FolderStore) -> None:
    assert re.fullmatch(r"[0-9a-f]{32}", db.create_folder("One", CASE, "house", 22))


@pytest.mark.parametrize(
    "folder",
    [
        ABSENT,  # well formed, never created
        "abc",
        "A" * 32,
        "0" * 31 + "\n",
        "0" * 31 + "%0a",
        "%2e%2e",
        "0" * 33,
    ],
)
def test_unknown_or_malformed_folder_id_is_404(client: TestClient, folder: str) -> None:
    path = f"/f/{quote(folder, safe='')}"
    assert client.get(path).status_code == 404
    assert post(client, f"{path}/cards/1/status", "status=done").status_code == 404
    assert (
        post(client, f"{path}/cases", f"case_id={CASE}&chamber=house&district=22").status_code
        == 404
    )


def test_unknown_card_is_404(client: TestClient) -> None:
    path = create(client)
    assert post(client, f"{path}/cards/999/status", "status=done").status_code == 404
    assert post(client, f"{path}/cards/x/status", "status=done").status_code == 404


def test_folder_page_for_a_folder_with_no_live_cards_still_opens(
    db: store.FolderStore, client: TestClient, tmp_path: Path
) -> None:
    folder = db.create_folder("One", CASE, "house", 22)
    with closing(sqlite3.connect(tmp_path / "folders.db")) as connection, connection:
        connection.execute("UPDATE cards SET deleted_at = 't'")
    assert NOTICE in client.get(f"/f/{folder}").text


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ("chamber=house&district=22", CASE),
        ("case_id=no_such&chamber=house&district=22", CASE),
        (f"case_id={CASE}&chamber=mayor&district=22", "house"),
        (f"case_id={CASE}&chamber=house&district=52", "house"),
    ],
    ids=["no-case", "unknown-case", "bad-chamber", "district-past-the-chamber"],
)
def test_bad_save_form_is_refused_naming_the_valid_choices(
    client: TestClient, tmp_path: Path, body: str, named: str
) -> None:
    for path in ("/folders", f"{create(client)}/cases"):
        before = len(rows(tmp_path / "folders.db", "SELECT id FROM cards"))
        response = post(client, path, body)
        assert response.status_code == 422
        assert named in response.json()["detail"]
        assert len(rows(tmp_path / "folders.db", "SELECT id FROM cards")) == before


@pytest.mark.parametrize(
    ("action", "body", "named"),
    [
        ("priority", "priority=urgent&reason=x", "high, normal, low"),
        ("priority", "reason=x", "high, normal, low"),
        ("priority", "priority=high", "1 to 200"),
        ("priority", "priority=high&reason=", "1 to 200"),
        ("priority", "priority=high&reason=+++", "1 to 200"),
        ("priority", f"priority=high&reason={'x' * 201}", "1 to 200"),
        ("priority", "priority=high&reason=a%0Ab", "one line"),
        ("status", "status=new", "idea, contacted, planned, done"),
        ("status", "", "idea, contacted, planned, done"),
    ],
    ids=[
        "unknown-priority",
        "no-priority",
        "no-reason",
        "empty-reason",
        "blank-reason",
        "long-reason",
        "two-line-reason",
        "unknown-status",
        "no-status",
    ],
)
def test_bad_card_form_is_refused_naming_the_rule(
    client: TestClient, action: str, body: str, named: str
) -> None:
    path = create(client)
    response = post(client, f"{path}/cards/{card_id(client, path)}/{action}", body)
    assert response.status_code == 422
    assert named in response.json()["detail"]
    assert "Priority: normal" in client.get(path).text and "Status: idea" in client.get(path).text


def test_a_reason_of_exactly_200_characters_is_kept(client: TestClient) -> None:
    path = create(client)
    post(
        client, f"{path}/cards/{card_id(client, path)}/priority", f"priority=low&reason={'x' * 200}"
    )
    assert "x" * 200 in client.get(path).text


def test_reason_is_escaped_on_the_page(client: TestClient) -> None:
    path = create(client)
    post(client, f"{path}/cards/{card_id(client, path)}/priority", "priority=low&reason=%3Cb%3Ex")
    assert "<b>x" not in client.get(path).text


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_store_path_is_mandatory_and_nothing_falls_back(
    flag: Flag, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    client = flag("on")
    if value is None:
        monkeypatch.delenv("KYD_FOLDERS_DB")
    else:
        monkeypatch.setenv("KYD_FOLDERS_DB", value)
    response = post(client, "/folders", f"case_id={CASE}&chamber=house&district=22")
    assert response.status_code == 503
    assert "KYD_FOLDERS_DB" in response.json()["detail"]
    assert client.get(f"/f/{ABSENT}").status_code == 503
    assert not (tmp_path / "folders.db").exists()


# --- the store refuses bad input before touching SQLite ---


@pytest.fixture
def no_sqlite(db: store.FolderStore, monkeypatch: pytest.MonkeyPatch) -> store.FolderStore:
    def refuse(_store: store.FolderStore) -> sqlite3.Connection:
        raise AssertionError("validation must run before the store opens SQLite")

    monkeypatch.setattr(store.FolderStore, "_connect", refuse)
    return db


Call = Callable[[store.FolderStore], object]
GOOD = "0" * 32


# Each call breaks one argument; `validate_call` reports it by position, `self` being 0.
REFUSED: list[tuple[Call, int]] = [
    (lambda s: s.get_folder("short"), 1),
    (lambda s: s.save_case("short", CASE, "house", 22), 1),
    (lambda s: s.set_status("short", 1, "done"), 1),
    (lambda s: s.set_priority("short", 1, "high", "x"), 1),
    (lambda s: s.set_status(GOOD, 0, "done"), 2),
    (lambda s: s.set_status(GOOD, 1, "new"), 3),  # pyright: ignore[reportArgumentType] -- the refusal under test
    (lambda s: s.set_priority(GOOD, 1, "urgent", "x"), 3),  # pyright: ignore[reportArgumentType] -- the refusal under test
    (lambda s: s.set_priority(GOOD, 1, "high", "x" * 201), 4),
    (lambda s: s.set_priority(GOOD, 1, "high", ""), 4),
    (lambda s: s.set_priority(GOOD, 1, "high", "a\nb"), 4),
    (lambda s: s.save_case(GOOD, "Not-An-Id", "house", 22), 2),
    (lambda s: s.save_case(GOOD, CASE, "mayor", 22), 3),  # pyright: ignore[reportArgumentType] -- the refusal under test
    (lambda s: s.save_case(GOOD, CASE, "house", 0), 4),
    (lambda s: s.create_folder("", CASE, "house", 22), 1),
    (lambda s: s.create_folder("x" * 121, CASE, "house", 22), 1),
]


@pytest.mark.parametrize(("call", "position"), REFUSED)
def test_store_validates_before_sqlite(
    no_sqlite: store.FolderStore, call: Call, position: int
) -> None:
    with pytest.raises(ValidationError) as error:
        call(no_sqlite)
    assert [e["loc"][-1] for e in error.value.errors()] == [position]


def test_save_case_on_an_unknown_folder_is_refused(db: store.FolderStore) -> None:
    with pytest.raises(store.FolderNotFoundError):
        db.save_case(ABSENT, CASE, "house", 22)


def test_a_write_past_the_ceiling_is_a_capacity_refusal(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "folders.db"
    capped = store.FolderStore(path, state(), store.Limits(max_db_bytes=LIMIT))
    capped.initialize()
    with pytest.raises(store.CapacityError, match="database size"):
        for number in range(20000):
            capped.create_folder("x" * 120, CASE, "house", 1 + number % 51)
    assert len(rows(path, "SELECT id FROM folders")) == len(rows(path, "SELECT id FROM cards"))


def test_folder_and_first_card_commit_together(
    db: store.FolderStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = store.now
    stamps = iter([real()])  # enough for the folder row, not for its card

    def clock() -> str:
        try:
            return next(stamps)
        except StopIteration:
            raise RuntimeError("clock failed after the folder row") from None

    monkeypatch.setattr(store, "now", clock)
    with pytest.raises(RuntimeError, match="after the folder row"):
        db.create_folder("One", CASE, "house", 22)
    monkeypatch.setattr(store, "now", real)
    db.initialize()
    assert rows(tmp_path / "folders.db", "SELECT id FROM folders") == []


# --- one schema step ---


def test_schema_is_one_step_with_the_journey_status_words() -> None:
    assert len(store.MIGRATIONS) == 1
    assert "'contacted'" in store.MIGRATIONS[0]
    assert "'planned'" in store.MIGRATIONS[0]
    assert "'in_progress'" not in store.MIGRATIONS[0]


# --- the browser ---


@pytest.fixture
def live_folders(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shipped_facts: str
) -> str:
    """The in-process server with the shipped `preview` flag and a private store file."""
    config.write_text('outreach = "on"\nfolders = "preview"\n', encoding="utf-8")
    monkeypatch.setenv("KYD_FOLDERS_DB", str(tmp_path / "folders.db"))
    return shipped_facts


def test_browser_saves_sets_and_reloads_the_same_values(page: Page, live_folders: str) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 1440)
    page.get_by_role("button", name=COPY["save_label"]).click()
    page.wait_for_url("**/f/*")
    assert NOTICE in page.inner_text("main")
    assert axe_problems(page) == []
    url = page.url

    page.select_option("select[name=priority]", "high")
    page.fill("input[name=reason]", "Office outreach week")
    page.get_by_role("button", name="Set priority").click()
    page.get_by_text("Priority: high").wait_for()
    assert page.url == url  # an htmx partial update, not a page load

    page.select_option("select[name=status]", "contacted")
    page.get_by_role("button", name="Set status").click()
    page.get_by_text("Status: contacted").wait_for()

    page.reload()
    summary = page.inner_text(".folder-summary")
    assert "Priority: high" in summary
    assert "Office outreach week" in summary
    assert "Status: contacted" in summary
    assert page.input_value("select[name=priority]") == "high"
    assert page.input_value("input[name=reason]") == "Office outreach week"
    assert page.input_value("select[name=status]") == "contacted"
    assert axe_problems(page) == []


def test_keyboard_alone_completes_the_status_change_and_keeps_focus(
    page: Page, live_folders: str
) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 390)
    page.get_by_role("button", name=COPY["save_label"]).focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/f/*")

    page.focus("select[name=status]")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent") == "Set status"
    page.keyboard.press("Enter")
    page.get_by_text("Status: contacted").wait_for()
    assert page.evaluate("document.activeElement.textContent") == "Set status"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_copy_button_copies_the_folder_link(page: Page, live_folders: str) -> None:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 1440)
    page.get_by_role("button", name=COPY["save_label"]).click()
    page.wait_for_url("**/f/*")
    page.locator("button.copy-link").click()
    page.get_by_text("Link copied").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == page.url


def test_demo_steps_run_as_written(page: Page, live_folders: str) -> None:
    """The commit's `Demo:` block, step for step, on the shipped `preview` flag."""
    page.goto(f"{live_folders}/brief/house/22?preview=1")
    page.click("text=Save to folder")
    page.get_by_text(NOTICE).wait_for()
    page.select_option("select[name=priority]", "high")
    page.fill("input[name=reason]", "Office outreach week")
    page.click("text=Set priority")
    page.get_by_text("Priority: high").wait_for()
    page.select_option("select[name=status]", "contacted")
    page.click("text=Set status")
    page.get_by_text("Status: contacted").wait_for()
    page.click("text=Reopen this folder's link")
    page.get_by_text("Priority: high").wait_for()
    page.get_by_text("Status: contacted").wait_for()
