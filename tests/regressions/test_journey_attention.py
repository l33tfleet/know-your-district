"""#290: saved timestamps and deterministic, folder-scoped attention after reopening."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page, expect

from app.folders import store
from tests.regressions.test_journey_folder_save import Flag, client, create, flag, folder_store
from tests.regressions.test_wo97_brief_page import parse
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
TODAY = date(2026, 11, 6)


def test_folder_routes_defer_case_loading_to_startup() -> None:
    program = (
        "import sys\n"
        "import app.folders.routes\n"
        "assert 'app.cases' not in sys.modules, 'folder routes loaded cases before startup'\n"
        "from app.main import validate_startup\n"
        "validate_startup()\n"
        "assert 'app.cases' in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def card(
    identity: int = 1,
    *,
    priority: store.Priority = "normal",
    status: store.Status = "idea",
    created: str = "2026-10-01",
    changed: str = "2026-11-03",
) -> store.Card:
    return store.Card.model_validate(
        {
            "id": identity,
            "case_id": "snap_no_receipt",
            "chamber": "house",
            "district": 22,
            "priority": priority,
            "status": status,
            "reason": None,
            "created_at": f"{created}T09:00:00+00:00",
            "updated_at": f"{changed}T09:00:00+00:00",
        }
    )


def note(day: str, card_id: int = 1) -> store.Note:
    return store.Note(id=1, card_id=card_id, dated=day, body="Outreach planned.")


def test_timestamp_readback_preserves_creation_and_latest_change(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "now", lambda: "2026-11-01T09:00:00+00:00")
    db = folder_store(tmp_path / "folders.db")
    folder = db.create_folder("Office", "snap_no_receipt", "house", 22)
    first = db.get_folder(folder).cards[0].model_dump()
    assert first["created_at"] == first["updated_at"] == "2026-11-01T09:00:00+00:00"
    monkeypatch.setattr(store, "now", lambda: "2026-11-03T12:00:00+00:00")
    db.set_priority(folder, first["id"], "high", None)
    changed = db.get_folder(folder).cards[0].model_dump()
    assert changed["created_at"] == first["created_at"]
    assert changed["updated_at"] == "2026-11-03T12:00:00+00:00"
    monkeypatch.setattr(store, "now", lambda: "2026-11-04T15:00:00+00:00")
    db.set_status(folder, first["id"], "planned")
    reopened = folder_store(tmp_path / "folders.db").get_folder(folder).cards[0].model_dump()
    assert reopened["created_at"] == first["created_at"]
    assert reopened["updated_at"] == "2026-11-04T15:00:00+00:00"


def test_high_priority_idea_makes_first_contact() -> None:
    from app.folders.attention import needs_attention

    saved = card(priority="high", created="2026-11-03")
    item = needs_attention([saved], [], TODAY)[0]
    assert item.case == saved
    assert item.next_step == "Make first contact"
    assert item.reason == "High priority, still an idea, saved 3 days ago."


@pytest.mark.parametrize("status", ["contacted", "planned"])
@pytest.mark.parametrize(
    "days,step", [(13, "Review next step"), (14, "Follow up"), (15, "Follow up")]
)
def test_follow_up_uses_latest_note_and_includes_the_14_day_boundary(
    status: store.Status, days: int, step: str
) -> None:
    from datetime import timedelta

    from app.folders.attention import needs_attention

    latest = TODAY - timedelta(days=days)
    item = needs_attention(
        [card(status=status)], [note(latest.isoformat()), note("2026-10-01")], TODAY
    )[0]
    assert item.next_step == step
    assert f"{days} days since the last note" in item.reason
    assert status in item.reason.lower()
    assert "Normal priority" in item.reason


@pytest.mark.parametrize(
    "created,step", [("2026-10-24", "Review next step"), ("2026-10-23", "Follow up")]
)
def test_follow_up_without_notes_counts_from_when_the_case_was_saved(
    created: str, step: str
) -> None:
    from app.folders.attention import needs_attention

    item = needs_attention([card(status="planned", created=created)], [], TODAY)[0]
    assert item.next_step == step
    assert "no notes" in item.reason
    days = (TODAY - date.fromisoformat(created)).days
    assert f"saved {days} days ago" in item.reason


def test_notes_on_another_case_do_not_reset_follow_up() -> None:
    from app.folders.attention import needs_attention

    assert (
        needs_attention([card(status="contacted")], [note("2026-11-06", 2)], TODAY)[0].next_step
        == "Follow up"
    )


def test_remaining_cases_sort_by_priority_then_oldest_change() -> None:
    from app.folders.attention import needs_attention

    cards = [
        card(5, priority="low", changed="2026-10-01"),
        card(4, changed="2026-11-04"),
        card(3, changed="2026-11-01"),
        card(2, status="planned", created="2026-11-01", priority="high"),
        card(6, priority="low", status="contacted"),
        card(1, priority="high"),
    ]
    items = needs_attention(cards, [], TODAY)
    assert [item.case.id for item in items] == [1, 6, 2, 3, 4, 5]
    assert items[2].next_step == "Review next step"
    assert "High priority, status planned" in items[2].reason
    assert "changed 3 days ago" in items[2].reason


def test_done_cases_leave_the_list_and_empty_input_is_empty() -> None:
    from app.folders.attention import needs_attention

    assert needs_attention([card(status="done", priority="high")], [], TODAY) == []
    assert needs_attention([], [], TODAY) == []


@pytest.mark.parametrize("status", ["idea", "contacted"])
def test_urgent_groups_also_use_priority_then_oldest_change(status: store.Status) -> None:
    from app.folders.attention import needs_attention

    cards = [
        card(1, status=status, priority="high", changed="2026-11-04"),
        card(3, status=status, priority="high", changed="2026-11-01"),
        card(2, status="contacted", priority="low", changed="2026-10-01"),
    ]
    assert [item.case.id for item in needs_attention(cards, [], TODAY)] == [3, 1, 2]


def test_saved_priority_reason_is_quoted_and_single_day_reads_naturally() -> None:
    from app.folders.attention import needs_attention

    saved = card(priority="high", created="2026-11-05").model_copy(
        update={"reason": "Office outreach week"}
    )
    item = needs_attention([saved], [], TODAY)[0]
    assert "saved 1 day ago" in item.reason
    assert item.reason.endswith("Saved priority reason: Office outreach week")


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
    page.get_by_text("Priority: High. Status: Idea.", exact=True).wait_for()
    page.get_by_text("Reopen this folder's link", exact=True).click()
    attention = page.get_by_role("region", name="Needs attention", exact=True)
    expect(attention).to_contain_text("Make first contact")
    expect(attention).to_contain_text("High priority, still an idea")
    expect(attention.get_by_role("link")).to_contain_text("SNAP")
    page.select_option("select[name=status]", "done")
    page.get_by_text("Priority: High. Status: Done.", exact=True).wait_for()
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


def test_attention_refresh_preserves_preview_and_uses_the_folder_get(flag: Flag) -> None:
    client = flag("preview")
    path = create(client, "?preview=1") + "?preview=1"
    document = parse(client.get(path).text)
    forms = [form for form in document.find_all("form") if "What needs attention?" in form.text]
    assert len(forms) == 1
    form = forms[0]
    assert form.attrs["method"].lower() == "get"
    assert form.attrs["action"].partition("?")[0] == path.partition("?")[0]
    assert form.one("button").attrs["type"] == "submit"
    assert form.one("input", name="preview").attrs["value"] == "1"
    assert client.get(form.attrs["action"], params={"preview": "1"}).status_code == 200
    assert client.get(path.partition("?")[0]).status_code == 404


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
    page.get_by_text("Priority: High. Status: Idea.", exact=True).wait_for()
    page.get_by_role("combobox", name="Status").select_option(label="Planned")
    page.get_by_text("Priority: High. Status: Planned.", exact=True).wait_for()
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
