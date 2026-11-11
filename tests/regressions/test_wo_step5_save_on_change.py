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
from playwright.sync_api import Page  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from pydantic import ValidationError

from app.copy import load_copy
from app.folders import store
from tests.regressions.test_journey_folder_save import (
    BRIEF,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    CASE,
    COPY,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    NOTICE,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    STATE_DIR,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
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
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page  # noqa: F401  # pyright: ignore[reportUnusedImport]  # only #347's superseded test used it
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


def test_an_empty_reason_clears_one_that_was_kept(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    endpoint = f"{path}/cards/{card_id(client, path)}/priority"
    post(client, endpoint, "priority=low&reason=Asked+first")
    assert "(Asked first)" in client.get(path).text
    post(client, endpoint, "priority=high&reason=")
    assert rows(tmp_path / "folders.db", "SELECT priority, reason FROM cards") == [("high", None)]


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
