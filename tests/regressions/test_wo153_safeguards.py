"""#225, step 2 of #153: the safeguards around a folder, whose link is its only credential.

Dormant by decision: no route uses `FolderService`, no production app installs the guards and
nothing schedules cleanup. So the store and service are driven directly, and the HTTP and logging
guards run in a temporary app. Routes, rendering and scheduling are #226, #227 and #228.
"""

import ast
import logging
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from uvicorn.logging import AccessFormatter

from app import features
from app.folders import pii, retention, service, store
from app.folders.service import FolderHttpGuard, FolderService
from app.page_state import PageState, page_state

ROOT = Path(__file__).resolve().parents[2]
SECRET = b"k" * 32
CASE = "case_one"
IP = "203.0.113.7"
OTHER_IP = "203.0.113.8"
NOTE = "Asked the office to follow up in spring."
START = datetime(2026, 1, 1, tzinfo=UTC)


def state() -> PageState:
    result = page_state("house", "22")
    assert result is not None
    return result


class Clock:
    def __init__(self) -> None:
        self.moment = START

    def __call__(self) -> str:
        return self.moment.isoformat(timespec="seconds")

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(store, "now", fake)
    return fake


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "features.toml"
    config.write_text('folders = "on"\n', encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", config)
    return tmp_path / "folders.db"


@pytest.fixture
def db(db_path: Path) -> store.FolderStore:
    folder_store = store.FolderStore(db_path, state())
    folder_store.initialize()
    return folder_store


@pytest.fixture
def folders(db: store.FolderStore) -> FolderService:
    return FolderService(db, SECRET)


def rows(path: Path, query: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return [tuple(row) for row in db.execute(query)]


def new_folder(db: store.FolderStore, name: str = "Kalihi") -> tuple[str, int]:
    folder_id = db.create_folder(name, CASE, "house", 22)
    return folder_id, db.get_folder(folder_id).cards[0].id


def add_note(folders: FolderService, folder_id: str, card: int, body: str = NOTE) -> int:
    return folders.add_note(folder_id, card, body, folders.confirmation(folder_id, body), IP)


def bodies(db: store.FolderStore, folder_id: str) -> list[str]:
    return [note.body for note in db.list_notes(folder_id)]


Write = Callable[[store.FolderStore, str, int], object]


# --- ids and folder isolation ---


def test_folder_ids_are_128_bits_from_secrets(
    db: store.FolderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []
    real = secrets.token_hex

    def spy(nbytes: int) -> str:
        sizes.append(nbytes)
        return real(nbytes)

    monkeypatch.setattr(store.secrets, "token_hex", spy)
    folder_id = store.new_folder_id()
    assert sizes == [16]
    assert len(folder_id) == 32
    assert int(folder_id, 16) >= 0


def test_another_folder_cannot_read_or_write_this_folders_notes(
    db: store.FolderStore, folders: FolderService
) -> None:
    mine, my_card = new_folder(db)
    theirs, their_card = new_folder(db, "Other")
    note = add_note(folders, mine, my_card)

    assert bodies(db, theirs) == []
    with pytest.raises(store.FolderNotFoundError):
        db.add_note(theirs, my_card, "Written across folders", True)
    with pytest.raises(store.FolderNotFoundError):
        db.edit_note(theirs, note, "Edited across folders", True)
    assert bodies(db, mine) == [NOTE]
    assert their_card != my_card


def test_notes_are_listed_only_for_a_live_folder(db: store.FolderStore) -> None:
    with pytest.raises(store.FolderNotFoundError):
        db.list_notes("0" * 32)


def test_a_note_edit_cannot_reach_a_missing_note(db: store.FolderStore) -> None:
    folder_id, _ = new_folder(db)
    with pytest.raises(store.FolderNotFoundError):
        db.edit_note(folder_id, 999, NOTE, True)


# --- rotating the link ---


def test_rotation_kills_the_old_link_and_keeps_the_contents(
    db: store.FolderStore, folders: FolderService, db_path: Path
) -> None:
    old, card = new_folder(db)
    db.set_status(old, card, "contacted")
    add_note(folders, old, card)

    new = folders.rotate_link(old, IP)

    assert new != old
    kept = db.get_folder(new)
    assert (kept.name, [(c.id, c.status) for c in kept.cards]) == ("Kalihi", [(card, "contacted")])
    assert bodies(db, new) == [NOTE]
    assert rows(db_path, "SELECT COUNT(*) FROM folders") == [(1,)]
    with pytest.raises(store.FolderNotFoundError):
        db.get_folder(old)
    with pytest.raises(store.FolderNotFoundError):
        db.list_notes(old)
    with pytest.raises(store.FolderNotFoundError):
        db.set_status(old, card, "done")
    with pytest.raises(store.FolderNotFoundError):
        db.add_note(old, card, "Through the old link", True)
    with pytest.raises(store.FolderNotFoundError):
        db.save_case(old, CASE, "house", 23)


def test_rotation_moves_trashed_cards_too(db: store.FolderStore, db_path: Path) -> None:
    old, card = new_folder(db)
    with closing(sqlite3.connect(db_path)) as raw, raw:
        raw.execute("UPDATE cards SET deleted_at = 't' WHERE id = ?", (card,))
    new = db.rotate_link(old)
    assert rows(db_path, "SELECT folder_id FROM cards") == [(new,)]


def test_rotating_an_unknown_link_is_refused(db: store.FolderStore) -> None:
    with pytest.raises(store.FolderNotFoundError):
        db.rotate_link("0" * 32)


def test_a_failed_rotation_changes_nothing(
    db: store.FolderStore, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, _ = new_folder(db)
    monkeypatch.setattr(store, "new_folder_id", lambda: old)  # the insert hits the primary key
    with pytest.raises(sqlite3.IntegrityError):
        db.rotate_link(old)
    assert db.get_folder(old).name == "Kalihi"


# --- note text ---


def test_a_note_of_exactly_1000_characters_is_kept(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    add_note(folders, folder_id, card, "x" * 1000)
    assert bodies(db, folder_id) == ["x" * 1000]


def test_a_note_of_1001_characters_is_refused(
    db: store.FolderStore, folders: FolderService, db_path: Path
) -> None:
    folder_id, card = new_folder(db)
    with pytest.raises(service.NoteRefusedError):
        folders.confirmation(folder_id, "x" * 1001)
    with pytest.raises(ValidationError):
        db.add_note(folder_id, card, "x" * 1001, True)
    assert rows(db_path, "SELECT COUNT(*) FROM notes") == [(0,)]


@pytest.mark.parametrize("body", ["", "   \n\t  ", "bell\x07", "line\u2028separator"])
def test_blank_or_control_text_is_refused(
    db: store.FolderStore, folders: FolderService, body: str
) -> None:
    folder_id, _ = new_folder(db)
    with pytest.raises(service.NoteRefusedError):
        folders.confirmation(folder_id, body)


def test_a_note_keeps_its_line_breaks_exactly(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    add_note(folders, folder_id, card, "First line\nSecond line ")
    assert bodies(db, folder_id) == ["First line\nSecond line "]


# --- personal details ---

BLOCKED = [
    ("phone", "Call (808) 555-0123 tomorrow"),
    ("phone", "808-555-0123"),
    ("phone", "808.555.0123"),
    ("phone", "808 555 0123"),
    ("phone", "8085550123"),
    ("phone", "+1 808 555 0123"),
    ("phone", "1-808-555-0123"),
    ("phone", "555-0123"),
    ("phone", "+44 20 7946 0958"),
    ("phone", "\uff18\uff10\uff18-\uff15\uff15\uff15-\uff10\uff11\uff12\uff13"),  # fullwidth digits
    ("phone", "808\u200b-555-0123"),  # a zero-width space
    ("email", "write to aunty.lei@example.org"),
    ("email", "AUNTY@EXAMPLE.ORG"),
    ("email", "aunty (at) example (dot) org"),
    ("email", "aunty [at] example.org"),
    ("email", "aunty\uff20example.org"),  # a fullwidth at sign
    ("address", "lives at 1234 Kapiolani Blvd"),
    ("address", "1234 kapiolani blvd"),
    ("address", "94-123 Waipahu St"),
    ("address", "45 Ala Moana Boulevard"),
    ("address", "7 Pali Highway"),
    ("address", "12 Pualani Way"),
    ("address", "300 Kaʻahumanu Place"),
    ("address", "PO Box 1234"),
    ("address", "P.O. Box 77"),
    ("address", "Apt 12"),
    ("address", "unit #4"),
]

ALLOWED = [
    "House District 22 asked about SNAP in the spring.",
    "Follow up on 3 programs with 211 after the 2024 survey.",
    "Table S1701_C01_001E covers 1,234 households.",
    "12 people came; the place was full and the way was clear.",
    "Hawaiʻi Island, Kauaʻi, Lānaʻi and Molokaʻi offices.",
    "Budget of $1,250,000 for 2025-2026.",
]


@pytest.mark.parametrize(("kind", "text"), BLOCKED)
def test_personal_details_are_recognized(kind: str, text: str) -> None:
    assert kind in pii.find(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_ordinary_office_text_is_not_blocked(text: str) -> None:
    assert pii.find(text) == ()


def test_blocking_runs_on_create(db: store.FolderStore, folders: FolderService) -> None:
    folder_id, _ = new_folder(db)
    with pytest.raises(service.PiiBlockedError) as error:
        folders.confirmation(folder_id, "Call 808-555-0123 or aunty@example.org")
    assert error.value.kinds == ("phone", "email")


def test_blocking_runs_on_edit(db: store.FolderStore, folders: FolderService) -> None:
    folder_id, card = new_folder(db)
    note = add_note(folders, folder_id, card)
    text = "Now at 1234 Kapiolani Blvd"
    token = folders.confirmation(folder_id, NOTE)
    with pytest.raises(service.PiiBlockedError):
        folders.edit_note(folder_id, note, text, token, IP)
    assert bodies(db, folder_id) == [NOTE]


def test_confirmation_never_overrides_blocking(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    text = "Call 808-555-0123"
    forged = pii.confirmation_token(SECRET, folder_id, text)  # even a correctly made token
    with pytest.raises(service.PiiBlockedError):
        folders.add_note(folder_id, card, text, forged, IP)
    assert bodies(db, folder_id) == []


PERSONAL_WRITES: list[Write] = [
    lambda db, folder, card: db.add_note(folder, card, "Call 808-555-0123", True),
    lambda db, folder, card: db.set_priority(folder, card, "high", "Call 808-555-0123"),
]


@pytest.mark.parametrize("write", PERSONAL_WRITES, ids=["note", "reason"])
def test_the_store_refuses_personal_details_whatever_the_caller(
    db: store.FolderStore, write: Write, db_path: Path
) -> None:
    folder_id, card = new_folder(db)
    with pytest.raises(ValidationError):
        write(db, folder_id, card)
    assert rows(db_path, "SELECT reason FROM cards") == [(None,)]
    assert rows(db_path, "SELECT COUNT(*) FROM notes") == [(0,)]


def test_the_store_refuses_personal_details_in_a_folder_name(
    db: store.FolderStore, db_path: Path
) -> None:
    with pytest.raises(ValidationError):
        db.create_folder("aunty@example.org", CASE, "house", 22)
    assert rows(db_path, "SELECT COUNT(*) FROM folders") == [(0,)]


def test_the_store_refuses_a_note_edit_with_personal_details(db: store.FolderStore) -> None:
    folder_id, card = new_folder(db)
    note = db.add_note(folder_id, card, NOTE, True)
    with pytest.raises(ValidationError):
        db.edit_note(folder_id, note, "Call 808-555-0123", True)


# --- confirmation ---


def test_a_note_needs_a_confirmation(db: store.FolderStore, folders: FolderService) -> None:
    folder_id, card = new_folder(db)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.add_note(folder_id, card, NOTE, None, IP)
    assert bodies(db, folder_id) == []


def test_changed_text_needs_a_new_confirmation(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    token = folders.confirmation(folder_id, NOTE)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.add_note(folder_id, card, f"{NOTE} ", token, IP)  # one trailing space
    folders.add_note(folder_id, card, NOTE, token, IP)
    assert bodies(db, folder_id) == [NOTE]


def test_an_edit_is_confirmed_against_its_new_text(
    db: store.FolderStore, folders: FolderService, db_path: Path
) -> None:
    folder_id, card = new_folder(db)
    note = add_note(folders, folder_id, card)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.edit_note(folder_id, note, "New words", folders.confirmation(folder_id, NOTE), IP)
    folders.edit_note(
        folder_id, note, "New words", folders.confirmation(folder_id, "New words"), IP
    )
    assert bodies(db, folder_id) == ["New words"]
    assert rows(db_path, "SELECT confirmed FROM notes") == [(1,)]


def test_a_garbled_confirmation_is_refused_not_a_crash(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.add_note(folder_id, card, NOTE, "ʻokina", IP)


def test_a_confirmation_belongs_to_one_folder(
    db: store.FolderStore, folders: FolderService
) -> None:
    first, _ = new_folder(db)
    second, card = new_folder(db)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.add_note(second, card, NOTE, folders.confirmation(first, NOTE), IP)


def test_a_confirmation_needs_the_server_secret(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    forged = pii.confirmation_token(b"z" * 32, folder_id, NOTE)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.add_note(folder_id, card, NOTE, forged, IP)


def test_the_store_has_no_unconfirmed_note(db: store.FolderStore) -> None:
    folder_id, card = new_folder(db)
    with pytest.raises(ValidationError):
        db.add_note(folder_id, card, NOTE, False)  # pyright: ignore[reportArgumentType] -- the refusal under test


# --- request limits ---


def create(folders: FolderService, ip: str = IP) -> str:
    return folders.create_folder("Kalihi", CASE, "house", 22, ip)


def test_folder_creation_is_limited_per_ip_durably(
    db: store.FolderStore, db_path: Path, clock: Clock
) -> None:
    for _ in range(service.CREATE_PER_IP.limit):
        create(FolderService(db, SECRET))
    restarted = FolderService(store.FolderStore(db_path, state()), SECRET)
    with pytest.raises(store.RateLimitedError) as error:
        create(restarted)
    assert error.value.retry_after_seconds == service.CREATE_PER_IP.window_seconds
    create(restarted, OTHER_IP)  # another address is not limited


def test_the_ip_limit_reopens_after_its_window(folders: FolderService, clock: Clock) -> None:
    for _ in range(service.CREATE_PER_IP.limit):
        create(folders)
    clock.advance(seconds=service.CREATE_PER_IP.window_seconds - 1)
    with pytest.raises(store.RateLimitedError):
        create(folders)
    clock.advance(seconds=1)
    create(folders)


def test_folder_creation_is_limited_globally(
    db: store.FolderStore, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    monkeypatch.setattr(
        service, "CREATE_GLOBAL", service.CREATE_GLOBAL.model_copy(update={"limit": 3})
    )
    folders = FolderService(db, SECRET)
    for number in range(3):
        create(folders, f"198.51.100.{number}")
    with pytest.raises(store.RateLimitedError):
        create(folders, "198.51.100.99")


def test_a_refused_address_does_not_spend_the_global_budget(
    folders: FolderService, db_path: Path, clock: Clock
) -> None:
    for _ in range(service.CREATE_PER_IP.limit):
        create(folders)
    with pytest.raises(store.RateLimitedError):
        create(folders)
    assert rows(db_path, "SELECT hits FROM rate_buckets WHERE scope = 'create:global'") == [
        (service.CREATE_PER_IP.limit,)
    ]


def test_a_refused_global_limit_stores_no_new_address(
    db: store.FolderStore, db_path: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    monkeypatch.setattr(
        service, "CREATE_GLOBAL", service.CREATE_GLOBAL.model_copy(update={"limit": 1})
    )
    folders = FolderService(db, SECRET)
    create(folders)
    with pytest.raises(store.RateLimitedError):
        create(folders, OTHER_IP)
    assert len(rows(db_path, "SELECT scope FROM rate_buckets")) == 2


def test_note_writes_are_limited_per_ip(
    db: store.FolderStore, folders: FolderService, clock: Clock
) -> None:
    folder_id, card = new_folder(db)
    for _ in range(service.WRITE_PER_IP.limit):
        add_note(folders, folder_id, card)
    with pytest.raises(store.RateLimitedError):
        add_note(folders, folder_id, card)


def test_a_refused_note_spends_no_limit(
    db: store.FolderStore, folders: FolderService, db_path: Path
) -> None:
    folder_id, card = new_folder(db)
    with pytest.raises(service.ConfirmationRequiredError):
        folders.add_note(folder_id, card, NOTE, None, IP)
    assert rows(db_path, "SELECT COUNT(*) FROM rate_buckets") == [(0,)]


def test_raw_addresses_are_never_stored(
    folders: FolderService, db_path: Path, clock: Clock
) -> None:
    create(folders)
    folders.throttle_write(OTHER_IP)
    scopes = [str(row[0]) for row in rows(db_path, "SELECT scope FROM rate_buckets")]
    assert len(scopes) == 3
    assert not any(IP in scope or OTHER_IP in scope for scope in scopes)
    with closing(sqlite3.connect(db_path)) as raw:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert IP.encode() not in db_path.read_bytes()


def test_the_address_hash_is_keyed(db: store.FolderStore, db_path: Path, clock: Clock) -> None:
    create(FolderService(db, SECRET))
    create(FolderService(db, b"z" * 32))
    assert len(rows(db_path, "SELECT scope FROM rate_buckets WHERE scope LIKE 'create:ip:%'")) == 2


# --- the secret ---


def test_the_secret_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(service.SECRET_ENV, "s" * 32)
    assert service.load_secret() == b"s" * 32


def test_a_missing_secret_stops_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(service.SECRET_ENV, raising=False)
    with pytest.raises(store.StoreConfigError, match=service.SECRET_ENV):
        service.load_secret()


def test_a_short_secret_stops_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(service.SECRET_ENV, "s" * 31)
    with pytest.raises(store.StoreConfigError, match="32"):
        service.load_secret()


# --- external path ---


def test_a_symlink_into_the_checkout_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "folders.db"
    link.symlink_to(ROOT / "data" / "folders.db")
    with pytest.raises(store.StoreConfigError, match="outside the checkout"):
        store.FolderStore(link, state())


# --- expiry ---

JUST_BEFORE = {"days": 179, "hours": 23, "minutes": 59, "seconds": 59}


def test_retention_is_180_days() -> None:
    assert timedelta(days=180) == retention.RETENTION


def test_a_folder_lives_until_180_days_after_its_last_write(
    db: store.FolderStore, clock: Clock
) -> None:
    folder_id, _ = new_folder(db)
    clock.advance(**JUST_BEFORE)
    assert db.get_folder(folder_id).name == "Kalihi"
    assert retention.cleanup(db).folders == 0
    clock.advance(seconds=1)
    with pytest.raises(store.FolderNotFoundError):
        db.get_folder(folder_id)  # expired even if the cleanup has not run
    with pytest.raises(store.FolderNotFoundError):
        db.set_status(folder_id, 1, "done")
    assert retention.cleanup(db).folders == 1


LIFE_WRITES: list[Write] = [
    lambda db, f, c: db.set_status(f, c, "done"),
    lambda db, f, c: db.set_priority(f, c, "high", "Asked first"),
    lambda db, f, c: db.save_case(f, "case_two", "house", 22),
    lambda db, f, c: db.add_note(f, c, NOTE, True),
]


@pytest.mark.parametrize("write", LIFE_WRITES, ids=["status", "priority", "case", "note"])
def test_a_write_extends_the_folders_life(
    db: store.FolderStore, clock: Clock, write: Write
) -> None:
    folder_id, card = new_folder(db)
    clock.advance(days=100)
    write(db, folder_id, card)
    clock.advance(days=100)
    assert db.get_folder(folder_id).name == "Kalihi"


def test_a_note_edit_extends_the_folders_life(db: store.FolderStore, clock: Clock) -> None:
    folder_id, card = new_folder(db)
    note = db.add_note(folder_id, card, NOTE, True)
    clock.advance(days=100)
    db.edit_note(folder_id, note, "Edited", True)
    clock.advance(days=100)
    assert db.get_folder(folder_id).name == "Kalihi"


def test_reading_does_not_extend_a_folders_life(db: store.FolderStore, clock: Clock) -> None:
    folder_id, _ = new_folder(db)
    clock.advance(days=100)
    db.get_folder(folder_id)
    clock.advance(days=80)
    with pytest.raises(store.FolderNotFoundError):
        db.get_folder(folder_id)


def test_cleanup_removes_a_folders_cards_and_notes_and_leaves_the_rest(
    db: store.FolderStore, db_path: Path, clock: Clock
) -> None:
    old, card = new_folder(db)
    db.add_note(old, card, "Secret words to purge", True)
    clock.advance(days=1)
    kept, _ = new_folder(db, "Kept")
    clock.advance(days=179)

    purged = retention.cleanup(db)

    assert purged.folders == 1
    assert rows(db_path, "SELECT id FROM folders") == [(kept,)]
    assert len(rows(db_path, "SELECT id FROM cards")) == 1
    assert rows(db_path, "SELECT COUNT(*) FROM notes") == [(0,)]
    stored = b"".join(p.read_bytes() for p in db_path.parent.glob("folders.db*"))
    assert b"Secret words to purge" not in stored


def test_cleanup_empties_the_trash_after_180_days(
    db: store.FolderStore, db_path: Path, clock: Clock
) -> None:
    gone, _ = new_folder(db, "Trashed folder")
    live, card = new_folder(db)
    db.save_case(live, "case_two", "house", 22)
    other_card = db.get_folder(live).cards[1].id
    note = db.add_note(live, card, NOTE, True)
    stamp = clock()
    with closing(sqlite3.connect(db_path)) as raw, raw:
        raw.execute("UPDATE folders SET deleted_at = ? WHERE id = ?", (stamp, gone))
        raw.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (stamp, other_card))
        raw.execute("UPDATE notes SET deleted_at = ? WHERE id = ?", (stamp, note))
    clock.advance(days=179)
    db.set_status(live, card, "done")  # the folder stays live; its trash ages on its own
    clock.advance(days=1)

    purged = retention.cleanup(db)

    assert (purged.folders, purged.cards, purged.notes) == (1, 1, 1)
    assert rows(db_path, "SELECT id FROM folders") == [(live,)]


def test_cleanup_drops_stale_rate_counters(
    folders: FolderService, db_path: Path, clock: Clock
) -> None:
    create(folders)
    clock.advance(seconds=store.RATE_BUCKET_TTL_SECONDS - 1)
    assert retention.cleanup(folders.store).rate_buckets == 0
    clock.advance(seconds=1)
    assert retention.cleanup(folders.store).rate_buckets == 2
    assert rows(db_path, "SELECT COUNT(*) FROM rate_buckets") == [(0,)]


def test_a_dry_run_reports_and_removes_nothing(
    db: store.FolderStore, db_path: Path, clock: Clock
) -> None:
    new_folder(db)
    clock.advance(days=180)
    assert retention.cleanup(db, dry_run=True).folders == 1
    assert rows(db_path, "SELECT COUNT(*) FROM folders") == [(1,)]


def test_cleanup_still_runs_when_the_file_is_past_its_ceiling(db_path: Path, clock: Clock) -> None:
    large = store.FolderStore(db_path, state())
    for number in range(400):
        large.create_folder("x" * 120, CASE, "house", 1 + number % 51)
    clock.advance(days=180)
    tight = store.FolderStore(db_path, state(), store.Limits(max_db_bytes=8192))
    assert retention.cleanup(tight).folders == 400


def test_cleanup_respects_the_flag(
    db: store.FolderStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "features.toml").write_text('folders = "off"\n', encoding="utf-8")
    with pytest.raises(store.FoldersDisabledError):
        retention.cleanup(db)


# --- the secret link stays out of errors and logs ---


def test_errors_carry_no_note_text_or_folder_id(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    private = "Private words about the office"
    with pytest.raises(ValidationError) as refused:
        db.add_note(folder_id, card, f"{private} {'x' * 1000}", True)
    assert private not in str(refused.value)
    assert folder_id not in str(refused.value)
    with pytest.raises(ValidationError) as bad_id:
        db.get_folder(f"{folder_id}?")
    assert folder_id not in str(bad_id.value)
    with pytest.raises(store.FolderNotFoundError) as unknown:
        db.get_folder("0" * 32)
    assert "0" * 32 not in str(unknown.value)
    with pytest.raises(service.PiiBlockedError) as blocked:
        folders.confirmation(folder_id, "Call 808-555-0123")
    assert "555" not in str(blocked.value)


def test_reprs_carry_no_note_text_or_folder_id(
    db: store.FolderStore, folders: FolderService
) -> None:
    folder_id, card = new_folder(db)
    add_note(folders, folder_id, card)
    assert folder_id not in repr(db.get_folder(folder_id))
    assert NOTE not in repr(db.list_notes(folder_id))


def test_no_model_or_tool_code_can_reach_folders() -> None:
    """Notes and links stay out of prompts: nothing behind the chat agent imports this package."""
    for package in ("app/agent", "app/tools"):
        for source in (ROOT / package).rglob("*.py"):
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                assert not any(name.startswith("app.folders") for name in names), source


ID = "a" * 32
PATH = f"/f/{ID}/cards/3/status"


def redacted(record: logging.LogRecord) -> logging.LogRecord:
    assert service.RedactFolderLinks().filter(record)
    return record


def record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, "f.py", 1, message, args, None)


def test_uvicorn_access_lines_lose_the_folder_path() -> None:
    line = redacted(record('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "POST", PATH, "1.1", 200))
    text = AccessFormatter(fmt="%(request_line)s %(status_code)s", use_colors=False).format(line)
    assert ID not in text
    assert text == "POST /f/[redacted]/cards/3/status HTTP/1.1 200 OK"


@pytest.mark.parametrize(
    "made",
    [
        record(f"GET {PATH}"),
        record("full link %s", f"https://example.org{PATH}?preview=1"),
        record("folder %s went away", ID),
        record("bad link /f/not-a-real-id/x"),
        record("%(link)s", {"link": PATH}),
    ],
    ids=["message", "argument", "bare-id", "any-segment", "mapping"],
)
def test_error_lines_lose_the_folder_path(made: logging.LogRecord) -> None:
    text = redacted(made).getMessage()
    assert ID not in text
    assert "not-a-real-id" not in text


def test_tracebacks_lose_the_folder_path() -> None:
    try:
        raise RuntimeError(f"failed on {PATH}")
    except RuntimeError as exc:
        line = logging.LogRecord("t", logging.ERROR, "f", 1, "boom", (), (type(exc), exc, None))
    line.stack_info = f"stack {PATH}"
    text = logging.Formatter().format(redacted(line))
    assert ID not in text
    assert "/f/[redacted]" in text


def test_redaction_keeps_numbers_for_the_formatter() -> None:
    assert redacted(record("%d of %s", 3, "x")).getMessage() == "3 of x"


@pytest.fixture
def clean_handler() -> Iterator[logging.Handler]:
    handler = logging.NullHandler()
    logger = logging.getLogger("uvicorn.access")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    for filter_ in list(logger.filters):
        logger.removeFilter(filter_)


def test_installing_redaction_covers_loggers_and_handlers_once(
    clean_handler: logging.Handler,
) -> None:
    service.install_log_redaction(("uvicorn.access",))
    service.install_log_redaction(("uvicorn.access",))
    assert len(clean_handler.filters) == 1
    assert len(logging.getLogger("uvicorn.access").filters) == 1


# --- HTTP guards in a temporary app ---


def guarded_app(trusted: str = "") -> TestClient:
    app = FastAPI()
    proxies = service.parse_trusted_proxies(trusted)

    @app.get("/f/{folder_id}")
    def read(folder_id: str) -> PlainTextResponse:
        return PlainTextResponse(folder_id, headers={"Cache-Control": "public, max-age=60"})

    @app.post("/f/{folder_id}")
    async def write(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    @app.post("/folders")
    async def make(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    @app.post("/brief")
    async def other(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    @app.get("/ip")
    def where(request: Request) -> PlainTextResponse:
        return PlainTextResponse(service.client_ip(request.scope, proxies))

    return TestClient(FolderHttpGuard(app, max_body_bytes=16), client=(IP, 50000))


PRIVATE = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex",
}


@pytest.mark.parametrize("target", [f"/f/{ID}", f"/f/{ID}/missing", "/f/"])
def test_folder_responses_are_private_even_when_refused(target: str) -> None:
    response = guarded_app().get(target)
    assert {name: response.headers[name] for name in PRIVATE} == PRIVATE


def test_a_refused_body_is_private_too() -> None:
    response = guarded_app().post("/folders", content=b"x" * 17)
    assert {name: response.headers[name] for name in PRIVATE} == PRIVATE


def test_other_pages_are_left_alone() -> None:
    response = guarded_app().get("/ip")
    assert not set(PRIVATE) & set(response.headers)


def test_a_body_at_the_cap_reaches_the_route_whole() -> None:
    assert guarded_app().post(f"/f/{ID}", content=b"x" * 16).text == "16"


@pytest.mark.parametrize("target", [f"/f/{ID}", "/folders"])
def test_a_body_past_the_cap_is_refused(target: str) -> None:
    assert guarded_app().post(target, content=b"x" * 17).status_code == 413


def test_a_chunked_body_past_the_cap_is_refused() -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(4):
            yield b"x" * 5

    assert guarded_app().post("/folders", content=chunks()).status_code == 413


def test_the_body_cap_covers_only_folder_routes() -> None:
    assert guarded_app().post("/brief", content=b"x" * 17).text == "17"


def test_the_default_cap_fits_a_fully_encoded_note() -> None:
    assert len(("%F0%9F%8C%BA" * 1000).encode()) + 200 < service.MAX_BODY_BYTES


def test_a_forwarded_header_from_an_untrusted_peer_is_ignored() -> None:
    client = guarded_app(trusted="10.0.0.0/8")
    assert client.get("/ip", headers={"X-Forwarded-For": "198.51.100.1"}).text == IP


def test_a_trusted_proxy_gives_the_hop_it_saw() -> None:
    client = guarded_app(trusted=f"{IP}/32, 10.0.0.0/8")
    spoofed = {"X-Forwarded-For": "1.1.1.1, 198.51.100.1, 10.0.0.2"}
    assert client.get("/ip", headers=spoofed).text == "198.51.100.1"


def test_a_malformed_hop_stops_the_walk() -> None:
    client = guarded_app(trusted=f"{IP}/32")
    response = client.get("/ip", headers={"X-Forwarded-For": "198.51.100.1, not-an-ip"})
    assert response.text == IP


def test_no_trusted_hop_header_means_the_peer() -> None:
    assert guarded_app(trusted=f"{IP}/32").get("/ip").text == IP


def peer(address: str | None) -> dict[str, object]:
    empty: list[tuple[bytes, bytes]] = []
    return {"type": "http", "headers": empty, "client": (address, 1) if address else None}


def test_an_unknown_peer_shares_one_bucket() -> None:
    assert service.client_ip(peer(None), ()) == "unknown"


def test_an_ipv6_client_is_counted_by_its_slash_64() -> None:
    first = service.client_ip(peer("2001:db8:1:2:aaaa::1"), ())
    second = service.client_ip(peer("2001:db8:1:2:bbbb::2"), ())
    assert first == second == "2001:db8:1:2::/64"


def test_a_mapped_ipv4_client_is_the_same_address() -> None:
    assert service.client_ip(peer(f"::ffff:{IP}"), ()) == IP


def test_a_bad_trusted_proxy_setting_fails_loudly() -> None:
    with pytest.raises(ValueError, match="nonsense"):
        service.parse_trusted_proxies("10.0.0.0/8, nonsense")


# --- nothing here adds a free-text contact ---


def test_the_store_has_no_contact_column(db_path: Path, db: store.FolderStore) -> None:
    for table in ("folders", "cards", "notes"):
        columns = [str(row[1]) for row in rows(db_path, f"PRAGMA table_info({table})")]
        assert not any("contact" in column or "phone" in column for column in columns)


@pytest.mark.parametrize(
    "suffix",
    [
        "way",
        "place",
        "pl",
        "court",
        "ct",
        "drive",
        "dr",
        "lane",
        "ln",
        "loop",
        "circle",
        "cir",
        "terrace",
        "ter",
    ],
)
@pytest.mark.parametrize("street", ["pualani", "PUALANI", "Pualani"])
def test_personal_addresses_are_blocked_regardless_of_capitalization(
    street: str,
    suffix: str,
) -> None:
    assert pii.find(f"12 {street} {suffix}") == ("address",)


def test_a_space_separated_local_phone_is_blocked() -> None:
    assert pii.find("Call 555 0123 tomorrow") == ("phone",)


@pytest.mark.parametrize("text", ["12 pualani way", "Call 555 0123 tomorrow"])
def test_contact_blocking_cannot_be_bypassed_on_create_or_edit(
    db: store.FolderStore,
    folders: FolderService,
    text: str,
) -> None:
    folder_id, card = new_folder(db)
    note = add_note(folders, folder_id, card)
    token = pii.confirmation_token(SECRET, folder_id, text)
    with pytest.raises(service.PiiBlockedError):
        folders.confirmation(folder_id, text)
    with pytest.raises(service.PiiBlockedError):
        folders.add_note(folder_id, card, text, token, IP)
    with pytest.raises(service.PiiBlockedError):
        folders.edit_note(folder_id, note, text, token, IP)
    with pytest.raises(ValidationError, match="Personal phone numbers, emails and addresses"):
        db.add_note(folder_id, card, text, True)
    with pytest.raises(ValidationError, match="Personal phone numbers, emails and addresses"):
        db.edit_note(folder_id, note, text, True)
    assert bodies(db, folder_id) == [NOTE]
