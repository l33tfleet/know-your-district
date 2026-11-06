"""#233: immutable journey seed, atomic refresh, and private visitor edits."""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.folders import demo, store
from app.folders.attention import needs_attention
from app.folders.service import FolderService
from tests.regressions.test_journey_folder_save import client, flag, folder_store, rows

__all__ = ["client", "flag"]
BODY = "Discuss outreach materials with community navigators."


@pytest.fixture
def seeded(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> store.FolderStore:
    monkeypatch.setenv("KYD_FOLDERS_SECRET", "s" * 32)
    db = folder_store(tmp_path / "folders.db")
    db.refresh_demo(demo.plan())
    return db


def test_preview_never_initializes_storage(client: TestClient, tmp_path: Path) -> None:
    command = [sys.executable, "-m", "app.folders.demo"]
    preview = subprocess.run(command, capture_output=True, text=True, check=True)
    assert not (tmp_path / "folders.db").exists()
    assert "--commit" in preview.stdout
    subprocess.run([*command, "--commit"], capture_output=True, text=True, check=True)
    db = folder_store(tmp_path / "folders.db")
    assert db.get_folder(store.DEMO_ID).cards
    before = rows(db.path, "SELECT * FROM folders")
    demo.main([])
    assert rows(db.path, "SELECT * FROM folders") == before


def test_refresh_is_stable_and_preserves_other_folders(seeded: store.FolderStore) -> None:
    other = seeded.create_folder("Other", "snap_no_receipt", "house", 22)
    original = seeded.get_folder(other)
    seed = seeded.get_folder(store.DEMO_ID)
    current = seed
    for _ in range(2):
        seeded.refresh_demo(demo.plan())
        current = seeded.get_folder(store.DEMO_ID)
        assert [(c.case_id, c.priority, c.status) for c in current.cards] == [
            (c.case_id, c.priority, c.status) for c in seed.cards
        ]
        assert seeded.get_folder(other) == original
    from datetime import date

    assert needs_attention(current.cards, seeded.list_notes(store.DEMO_ID), date(2026, 11, 6))


@pytest.mark.parametrize("htmx", [False, True])
@pytest.mark.parametrize("operation", ["save", "priority", "status", "add", "edit", "delete"])
def test_every_visitor_edit_forks_and_navigates(
    seeded: store.FolderStore, client: TestClient, operation: str, htmx: bool
) -> None:
    seed = seeded.get_folder(store.DEMO_ID)
    notes = seeded.list_notes(store.DEMO_ID)
    card, note = seed.cards[0].id, notes[0].id
    root = f"/f/{store.DEMO_ID}"
    endpoint, data = {
        "save": ("/cases", {"case_id": "snap_no_receipt", "chamber": "house", "district": "23"}),
        "priority": (f"/cards/{card}/priority", {"priority": "low"}),
        "status": (f"/cards/{card}/status", {"status": "done"}),
        "add": (f"/cards/{card}/notes", {"body": BODY}),
        "edit": (f"/notes/{note}", {"body": BODY}),
        "delete": (f"/notes/{note}/delete", {}),
    }[operation]
    if operation in ("add", "edit"):
        data["confirmation"] = FolderService(seeded, b"s" * 32).confirmation(store.DEMO_ID, BODY)
    response = client.post(root + endpoint, data=data, headers={"HX-Request": str(htmx).lower()})
    assert response.status_code == (200 if htmx else 303)
    target = response.headers["HX-Redirect" if htmx else "location"]
    assert target != root and target.startswith("/f/")
    copied = seeded.get_folder(target.removeprefix("/f/"))
    assert {c.id for c in copied.cards}.isdisjoint(c.id for c in seed.cards)
    copied_notes = seeded.list_notes(copied.id)
    assert {n.id for n in copied_notes}.isdisjoint(n.id for n in notes)
    assert seeded.get_folder(store.DEMO_ID) == seed  # visitor two sees the original
    assert seeded.list_notes(store.DEMO_ID) == notes
    assert client.get(root).status_code == client.get(target).status_code == 200
    assert "https://auw211.org/" in client.get(target).text
    if operation == "save":
        assert len(copied.cards) == len(seed.cards) + 1
    elif operation == "priority":
        assert copied.cards[0].priority == "low"
    elif operation == "status":
        assert copied.cards[0].status == "done"
    elif operation == "delete":
        assert not copied_notes
    else:
        assert BODY in [n.body for n in copied_notes]
    # Subsequent edits target the copy, and a refresh cannot erase the visitor's work.
    again = client.post(f"{target}/cards/{copied.cards[0].id}/status", data={"status": "planned"})
    assert again.headers["location"] == target
    edited = seeded.get_folder(copied.id)
    seeded.refresh_demo(demo.plan())
    assert seeded.get_folder(copied.id) == edited
    assert seeded.list_notes(copied.id) == copied_notes


@pytest.mark.parametrize(
    "data",
    [
        {"body": BODY},
        {"body": BODY, "confirmation": "bad"},
        {"body": "Call 808-555-0142", "confirmation": "bad"},
    ],
)
def test_drafts_and_refusals_do_not_fork(
    seeded: store.FolderStore, client: TestClient, data: dict[str, str]
) -> None:
    card = seeded.get_folder(store.DEMO_ID).cards[0].id
    before = rows(seeded.path, "SELECT * FROM folders")
    response = client.post(f"/f/{store.DEMO_ID}/cards/{card}/notes", data=data)
    assert response.status_code in (200, 422)
    assert rows(seeded.path, "SELECT * FROM folders") == before


def test_refresh_and_fork_roll_back_on_failure(seeded: store.FolderStore) -> None:
    seed = seeded.get_folder(store.DEMO_ID)
    notes = seeded.list_notes(store.DEMO_ID)
    # A failure after the old seed was removed must restore the complete original.
    with closing(sqlite3.connect(seeded.path)) as db:
        db.execute(
            "CREATE TRIGGER fail_seed BEFORE INSERT ON cards BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        seeded.refresh_demo(demo.plan())
    with (
        pytest.raises(sqlite3.IntegrityError, match="injected"),
        seeded.visitor_write(store.DEMO_ID),
    ):
        pass
    assert seeded.get_folder(store.DEMO_ID) == seed
    assert seeded.list_notes(store.DEMO_ID) == notes
    assert len(rows(seeded.path, "SELECT * FROM folders")) == 1


def test_direct_seed_mutation_is_refused(seeded: store.FolderStore) -> None:
    card = seeded.get_folder(store.DEMO_ID).cards[0].id
    with pytest.raises(store.FolderNotFoundError):
        seeded.set_status(store.DEMO_ID, card, "done")
    with pytest.raises(store.FolderNotFoundError):
        seeded.rotate_link(store.DEMO_ID)


def test_failed_edit_rolls_back_copy_and_remapped_records(seeded: store.FolderStore) -> None:
    before = [
        rows(seeded.path, f"SELECT * FROM {table}") for table in ("folders", "cards", "notes")
    ]
    with pytest.raises(store.FolderNotFoundError), seeded.visitor_write(store.DEMO_ID) as write:
        seeded.set_status(write.folder_id, write.card(999999), "done")
    assert before == [
        rows(seeded.path, f"SELECT * FROM {t}") for t in ("folders", "cards", "notes")
    ]


@pytest.mark.parametrize("htmx", [False, True])
@pytest.mark.parametrize("failure", ["text", "folder", "throttle"])
def test_confirmation_binding_and_throttle_precede_fork(
    seeded: store.FolderStore, client: TestClient, htmx: bool, failure: str
) -> None:
    service = FolderService(seeded, b"s" * 32)
    card = seeded.get_folder(store.DEMO_ID).cards[0].id
    original = store.DEMO_ID if failure != "folder" else "a" * 32
    token = service.confirmation(original, BODY)
    if failure == "throttle":
        for _ in range(60):
            service.throttle_write("unknown")
    response = client.post(
        f"/f/{store.DEMO_ID}/cards/{card}/notes",
        data={"body": BODY + (" Changed." if failure == "text" else ""), "confirmation": token},
        headers={"HX-Request": str(htmx).lower()},
    )
    assert response.status_code == (429 if failure == "throttle" else 422)
    assert len(rows(seeded.path, "SELECT * FROM folders")) == 1
