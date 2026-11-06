"""#290: saved timestamps and deterministic, folder-scoped attention after reopening."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page, expect

from app.folders import store
from tests.regressions.test_journey_folder_save import client, flag, folder_store
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
        expect(page.get_by_role("region", name="What needs attention")).to_be_visible()
    page.goto(paths[0])
    page.select_option("select[name=priority]", "high")
    page.get_by_text("Priority: High. Status: Idea.", exact=True).wait_for()
    page.get_by_text("Reopen this folder's link", exact=True).click()
    attention = page.get_by_role("region", name="What needs attention")
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
