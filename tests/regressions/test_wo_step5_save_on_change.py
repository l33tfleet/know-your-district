"""#346 (journey step 5, part 1): a card's priority and status save on change, no button.

The reason is optional now: an absent or empty one stores NULL and the summary shows no
parenthesis, while a reason that is given still meets every rule it met before. The store keeps
refusing an empty string, so only the route's explicit "no reason" reaches it as None.

Replaces, at least as strictly, four tests of `test_journey_folder_save.py` (#288) that pinned a
required reason or clicked the removed buttons.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page
from pydantic import ValidationError

from app.copy import load_copy
from app.folders import store
from tests.regressions.test_journey_folder_save import (
    BRIEF,
    CASE,
    COPY,
    NOTICE,
    STATE_DIR,
    card_id,
    client,
    create,
    db,
    flag,
    live_folders,
    post,
    rows,
)
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

# Reuse the #288 and WO122 fixtures unchanged.
__all__ = [
    "base_url",
    "browser",
    "client",
    "config",
    "db",
    "flag",
    "live_folders",
    "page",
    "shipped_facts",
]

PARTIAL = Path(__file__).resolve().parents[2] / "templates/partials/folder-case.html"


# --- the form ---


def test_the_card_partial_has_no_button_and_saves_on_change() -> None:
    assert "<button" not in PARTIAL.read_text(encoding="utf-8")


def test_each_card_form_saves_on_change_into_the_summary_only(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    document = parse(client.get(path).text)
    card_div = document.one("div", class_="folder-card")
    forms = card_div.find_all("form")
    assert len(forms) == 2
    assert card_div.find_all("button") == []
    for form in forms:
        assert form.attrs["hx-trigger"] == "change"
        assert form.attrs["hx-target"] == f"#live-{card}"
        assert form.attrs["hx-select"] == f"#summary-{card}"
        assert form.attrs["hx-swap"] == "innerHTML"
    reason = card_div.one("input", name="reason")
    assert "required" not in reason.attrs
    assert reason.attrs["maxlength"] == "200"


def test_the_reason_hint_says_the_reason_is_optional() -> None:
    words = load_copy()["folders"]
    assert "optional" in words["reason_hint"].lower()
    assert "set_priority" not in words and "set_status" not in words


# --- the route ---


@pytest.mark.parametrize(
    "body", ["priority=high", "priority=high&reason="], ids=["absent", "empty"]
)
def test_priority_with_no_reason_stores_null_and_shows_no_parenthesis(
    client: TestClient, tmp_path: Path, body: str
) -> None:
    path = create(client)
    card = card_id(client, path)
    saved = post(client, f"{path}/cards/{card}/priority", body)
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert rows(tmp_path / "folders.db", "SELECT priority, reason FROM cards") == [("high", None)]
    summary = parse(client.get(path).text).one("p", class_="folder-summary").text
    assert " ".join(summary.split()) == "Priority: high. Status: idea."
    assert "(" not in summary


def test_an_empty_reason_clears_one_that_was_kept(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    endpoint = f"{path}/cards/{card_id(client, path)}/priority"
    post(client, endpoint, "priority=low&reason=Asked+first")
    assert "(Asked first)" in client.get(path).text
    post(client, endpoint, "priority=high&reason=")
    assert rows(tmp_path / "folders.db", "SELECT priority, reason FROM cards") == [("high", None)]


def test_an_existing_reason_still_shows(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    post(client, f"{path}/cards/{card}/priority", "priority=high&reason=Asked+first")
    document = parse(client.get(path).text)
    summary = " ".join(document.one("p", class_="folder-summary").text.split())
    assert summary == "Priority: high (Asked first). Status: idea."
    assert 'value="Asked first"' in client.get(path).text


@pytest.mark.parametrize(
    ("action", "body", "named"),
    [
        ("priority", "priority=urgent&reason=x", "high, normal, low"),
        ("priority", "priority=urgent", "high, normal, low"),
        ("priority", "reason=x", "high, normal, low"),
        ("priority", "priority=high&reason=+++", "1 to 200"),
        ("priority", f"priority=high&reason={'x' * 201}", "1 to 200"),
        ("priority", "priority=high&reason=a%0Ab", "one line"),
        ("status", "status=new", "idea, contacted, planned, done"),
        ("status", "", "idea, contacted, planned, done"),
    ],
    ids=[
        "unknown-priority",
        "unknown-priority-no-reason",
        "no-priority",
        "blank-reason",
        "long-reason",
        "two-line-reason",
        "unknown-status",
        "no-status",
    ],
)
def test_bad_card_form_is_still_refused_naming_the_rule(
    client: TestClient, tmp_path: Path, action: str, body: str, named: str
) -> None:
    path = create(client)
    response = post(client, f"{path}/cards/{card_id(client, path)}/{action}", body)
    assert response.status_code == 422
    assert named in response.json()["detail"]
    assert rows(tmp_path / "folders.db", "SELECT priority, reason, status FROM cards") == [
        ("normal", None, "idea")
    ]


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
    """Carried over unchanged from #288: saving a case is not touched by this work order."""
    for path in ("/folders", f"{create(client)}/cases"):
        before = len(rows(tmp_path / "folders.db", "SELECT id FROM cards"))
        response = post(client, path, body)
        assert response.status_code == 422
        assert named in response.json()["detail"]
        assert len(rows(tmp_path / "folders.db", "SELECT id FROM cards")) == before


# --- the store ---


def test_store_writes_null_for_no_reason_and_still_refuses_an_empty_one(
    db: store.FolderStore, tmp_path: Path
) -> None:
    folder = db.create_folder("Office", CASE, "house", 22)
    card = db.get_folder(folder).cards[0].id
    db.set_priority(folder, card, "high", "Asked first")
    db.set_priority(folder, card, "low", None)
    assert db.get_folder(folder).cards[0].reason is None
    for text in ("", "   "):
        with pytest.raises(ValidationError):
            db.set_priority(folder, card, "high", text)
    assert rows(tmp_path / "folders.db", "SELECT priority, reason FROM cards") == [("low", None)]


# --- the browser ---


def test_browser_saves_priority_and_status_on_change_with_no_click(
    page: Page, live_folders: str
) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 1440)
    page.get_by_role("button", name=COPY["save_label"]).click()
    page.wait_for_url("**/f/*")
    assert axe_problems(page) == []
    url = page.url
    assert page.locator(".folder-card button").count() == 0

    page.select_option("select[name=priority]", "high")
    page.get_by_text("Priority: high. Status: idea.").wait_for()
    page.select_option("select[name=status]", "planned")
    page.get_by_text("Priority: high. Status: planned.").wait_for()
    assert page.url == url  # an htmx partial update, not a page load

    page.fill("input[name=reason]", "Office outreach week")
    page.locator("input[name=reason]").press("Tab")  # leaving the field is its change
    page.get_by_text("Priority: high (Office outreach week). Status: planned.").wait_for()

    page.reload()
    summary = " ".join(page.inner_text(".folder-summary").split())
    assert summary == "Priority: high (Office outreach week). Status: planned."
    assert page.input_value("select[name=priority]") == "high"
    assert page.input_value("input[name=reason]") == "Office outreach week"
    assert page.input_value("select[name=status]") == "planned"
    assert axe_problems(page) == []


def test_keyboard_change_saves_and_keeps_focus_on_the_select(page: Page, live_folders: str) -> None:
    open_page(page, f"{live_folders}{BRIEF}?preview=1", 390)
    page.get_by_role("button", name=COPY["save_label"]).focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/f/*")

    page.focus("select[name=status]")
    page.keyboard.press("ArrowDown")
    page.get_by_text("Status: contacted").wait_for()
    assert page.evaluate("document.activeElement.name") == "status"
    assert page.evaluate("document.activeElement.tagName") == "SELECT"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_demo_steps_run_as_written(page: Page, live_folders: str, tmp_path: Path) -> None:
    """The commit's `Demo:` block, step for step, on the shipped `preview` flag."""
    page.goto(f"{live_folders}/brief/house/22?preview=1")
    page.click("text=Save to folder")
    page.get_by_text(NOTICE).wait_for()
    page.select_option("select[name=priority]", "high")
    page.get_by_text("Priority: high").wait_for()
    page.select_option("select[name=status]", "planned")
    page.get_by_text("Status: planned").wait_for()
    page.click("text=Reopen this folder's link")
    page.get_by_text("Priority: high. Status: planned.").wait_for()
    assert (tmp_path / STATE_DIR / "folders.db").exists()
