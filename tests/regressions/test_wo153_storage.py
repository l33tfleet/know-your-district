"""#224 (step 1 of #153): the one writable store, `KYD_FOLDERS_DB`.

Pins the work order: restart keeps records, migrations repeat safely and roll back whole, the
200 cards / 1,000 notes / total-folder / database-size limits hold under concurrency, and the
file is 0600, WAL, busy-timed and outside the checkout. Nothing is written with the flag off.
"""

import sqlite3
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import features
from app.folders import models, store
from app.folders.models import CardState, CardStatus, NewCard, NewFolder, NewNote, Priority, RateHit
from app.folders.store import (
    AlreadySavedError,
    CapacityError,
    FolderNotFoundError,
    FoldersDisabledError,
    FolderStore,
    Limits,
    StoreConfigError,
)
from app.page_state import PageState, page_state
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[2]
HOUSE_22 = DistrictId(chamber="house", district=22)


def state(*, preview: bool = False) -> PageState:
    result = page_state("house", "22", preview=preview)
    assert result is not None
    return result


def set_flag(path: Path, monkeypatch: pytest.MonkeyPatch, status: str | None) -> None:
    config = path / "features.toml"
    config.write_text(f'folders = "{status}"\n' if status else "", encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", config)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    set_flag(tmp_path, monkeypatch, "on")
    return tmp_path / "folders.db"


def card(key: str = "snap-b22003", district: DistrictId = HOUSE_22) -> NewCard:
    return NewCard(card_key=key, district=district)


def note(body: str = "Asked the agency about hours.") -> NewNote:
    return NewNote(dated=date(2026, 10, 29), body=body)


def tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def user_version(path: Path) -> int:
    with sqlite3.connect(path) as db:
        return int(db.execute("PRAGMA user_version").fetchone()[0])


# Restart and migrations


def test_restart_preserves_every_record(db_path: Path) -> None:
    first = FolderStore(db_path, state())
    folder = first.create_folder(NewFolder(name="Kalihi follow-ups"))
    saved = first.add_card(folder.id, card())
    written = first.add_note(folder.id, saved.id, note())

    second = FolderStore(db_path, state())
    assert second.get_folder(folder.id) == folder.model_copy(
        update={"updated_at": second.get_folder(folder.id).updated_at}
    )
    assert second.list_cards(folder.id) == [saved]
    assert second.list_notes(folder.id, saved.id) == [written]


def test_opening_case_is_a_card_before_match_cards_exist(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Opening case"))
    saved = folder_store.add_card(folder.id, card("snap-b22003"))
    assert (saved.card_key, saved.district) == ("snap-b22003", HOUSE_22)


def test_migrations_repeat_safely(db_path: Path) -> None:
    for _ in range(3):
        FolderStore(db_path, state()).create_folder(NewFolder(name="Again"))
    assert user_version(db_path) == len(store.MIGRATIONS)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM folders").fetchone()[0] == 3


def test_failed_migration_rolls_back_whole(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Kept"))
    bad = "CREATE TABLE half_done (id INTEGER); INSERT INTO no_such_table VALUES (1);"
    monkeypatch.setattr(store, "MIGRATIONS", (*store.MIGRATIONS, bad))

    with pytest.raises(sqlite3.OperationalError, match="no_such_table"):
        folder_store.get_folder(folder.id)

    assert "half_done" not in tables(db_path)
    assert user_version(db_path) == 1


def test_next_migration_applies_once(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Kept"))
    monkeypatch.setattr(
        store, "MIGRATIONS", (*store.MIGRATIONS, "CREATE TABLE added (id INTEGER);")
    )

    assert folder_store.get_folder(folder.id).name == "Kept"
    assert folder_store.get_folder(folder.id).name == "Kept"
    assert "added" in tables(db_path)
    assert user_version(db_path) == 2


def test_newer_database_is_refused(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Kept"))
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(StoreConfigError, match="version 99"):
        folder_store.get_folder(folder.id)


def test_concurrent_first_open_migrates_once(db_path: Path) -> None:
    def create(index: int) -> str:
        return FolderStore(db_path, state()).create_folder(NewFolder(name=f"F{index}")).id

    with ThreadPoolExecutor(8) as pool:
        ids = list(pool.map(create, range(8)))
    assert len(set(ids)) == 8


def test_first_open_across_processes_is_clean(db_path: Path) -> None:
    program = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from app import features\n"
        "from app.folders.models import NewFolder\n"
        "from app.folders.store import FolderStore\n"
        "from app.page_state import page_state\n"
        "features.FEATURES_PATH = Path(sys.argv[2])\n"
        "state = page_state('house', '22')\n"
        "assert state is not None\n"
        "time.sleep(max(0, float(sys.argv[3]) - time.time()))\n"
        "FolderStore(Path(sys.argv[1]), state).create_folder(NewFolder(name='Race'))\n"
    )
    start = time.time() + 3
    config = db_path.with_name("features.toml")
    args = [sys.executable, "-c", program, str(db_path), str(config), str(start)]
    workers = [
        subprocess.Popen(args, cwd=ROOT, stderr=subprocess.PIPE, text=True) for _ in range(6)
    ]
    errors = [worker.communicate()[1] for worker in workers]
    assert errors == [""] * 6
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM folders").fetchone()[0] == 6
    assert list(db_path.parent.glob(".folders.db.*")) == []


def test_live_file_is_never_opened_outside_sqlite(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Closing a second descriptor of the live file would drop SQLite's POSIX locks.
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Locks"))

    def refuse(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("os.open on the live file")

    monkeypatch.setattr(store.os, "open", refuse)
    assert folder_store.get_folder(folder.id).name == "Locks"


# The file


def test_file_is_private_wal_and_busy_timed(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder_store.create_folder(NewFolder(name="Private"))
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600

    with closing(folder_store._connect()) as db:  # pyright: ignore[reportPrivateUsage] -- pins the connection's pragmas
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == store.BUSY_TIMEOUT_MS
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO rate_buckets VALUES ('sidecar', 0, 0)")
        for sidecar in ("-wal", "-shm"):
            assert stat.S_IMODE(Path(f"{db_path}{sidecar}").stat().st_mode) == 0o600


def test_loose_file_mode_is_refused(db_path: Path) -> None:
    db_path.touch(mode=0o644)
    db_path.chmod(0o644)
    with pytest.raises(StoreConfigError, match="0600"):
        FolderStore(db_path, state()).create_folder(NewFolder(name="Open"))


def test_file_in_checkout_is_refused(db_path: Path) -> None:
    with pytest.raises(StoreConfigError, match="outside the checkout"):
        FolderStore(ROOT / "data" / "folders.db", state())


def test_symlink_into_checkout_is_refused(db_path: Path) -> None:
    link = db_path.with_name("link.db")
    link.symlink_to(ROOT / "data" / "folders.db")
    with pytest.raises(StoreConfigError, match="outside the checkout"):
        FolderStore(link, state())


def test_relative_path_is_refused(db_path: Path) -> None:
    with pytest.raises(StoreConfigError, match="absolute"):
        FolderStore(Path("folders.db"), state())


def test_default_needs_the_environment_variable(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KYD_FOLDERS_DB", raising=False)
    with pytest.raises(StoreConfigError, match="KYD_FOLDERS_DB"):
        FolderStore.default(state())


def test_default_reads_the_environment_variable(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KYD_FOLDERS_DB", str(db_path))
    FolderStore.default(state()).create_folder(NewFolder(name="Env"))
    assert db_path.is_file()


def test_backup_restores_records(db_path: Path, tmp_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Backed up"))
    backup = tmp_path / "backup.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    backup.chmod(0o600)

    guide = (ROOT / "app/folders/__init__.py").read_text(encoding="utf-8")
    assert ".backup" in guide and "chmod 600" in guide
    assert FolderStore(backup, state()).get_folder(folder.id).name == "Backed up"


# The flag


@pytest.mark.parametrize("status", [None, "off"])
def test_flag_off_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str | None
) -> None:
    set_flag(tmp_path, monkeypatch, status)
    path = tmp_path / "folders.db"
    folder_store = FolderStore(path, state())
    with pytest.raises(FoldersDisabledError):
        folder_store.create_folder(NewFolder(name="Nope"))
    with pytest.raises(FoldersDisabledError):
        folder_store.get_folder("anything")
    assert not path.exists()


def test_preview_flag_follows_the_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_flag(tmp_path, monkeypatch, "preview")
    path = tmp_path / "folders.db"
    with pytest.raises(FoldersDisabledError):
        FolderStore(path, state()).create_folder(NewFolder(name="Nope"))
    assert not path.exists()
    FolderStore(path, state(preview=True)).create_folder(NewFolder(name="Preview"))
    assert path.is_file()


def test_turning_the_flag_off_stops_a_live_store(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder_store = FolderStore(db_path, state())
    folder_store.create_folder(NewFolder(name="Before"))
    set_flag(tmp_path, monkeypatch, "off")
    with pytest.raises(FoldersDisabledError):
        folder_store.create_folder(NewFolder(name="After"))


# Limits


def test_card_limit_is_200_per_folder(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Full"))
    other = folder_store.create_folder(NewFolder(name="Other"))
    for index in range(200):
        folder_store.add_card(folder.id, card(f"case-{index}"))

    with pytest.raises(CapacityError, match="200 cards"):
        folder_store.add_card(folder.id, card("case-200"))
    assert len(folder_store.list_cards(folder.id)) == 200
    folder_store.add_card(other.id, card("case-200"))


def test_note_limit_is_1000_per_folder_across_cards(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Full"))
    first = folder_store.add_card(folder.id, card("case-1"))
    second = folder_store.add_card(folder.id, card("case-2"))
    with sqlite3.connect(db_path) as db:
        db.executemany(
            "INSERT INTO notes (card_id, dated, body, confirmed, created_at, updated_at) "
            "VALUES (?, '2026-10-29', 'n', 0, 't', 't')",
            [(first.id if index % 2 else second.id,) for index in range(999)],
        )
    folder_store.add_note(folder.id, first.id, note("The thousandth."))

    with pytest.raises(CapacityError, match="1,000 notes"):
        folder_store.add_note(folder.id, second.id, note("One too many."))


def test_full_store_refuses_new_folders_cleanly(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state(), Limits(max_folders=2))
    kept = folder_store.create_folder(NewFolder(name="One"))
    folder_store.create_folder(NewFolder(name="Two"))

    with pytest.raises(CapacityError, match="2 folders"):
        folder_store.create_folder(NewFolder(name="Three"))

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM folders").fetchone()[0] == 2
    assert folder_store.get_folder(kept.id).name == "One"
    folder_store.delete_folder(kept.id)
    folder_store.create_folder(NewFolder(name="Room again"))


def test_database_size_limit_refuses_cleanly(db_path: Path) -> None:
    limit = 128 * 1024
    folder_store = FolderStore(db_path, state(), Limits(max_db_bytes=limit))
    made = [folder_store.create_folder(NewFolder(name="Kept")).id]
    with pytest.raises(CapacityError, match="database size"):
        for index in range(5000):
            made.append(folder_store.create_folder(NewFolder(name=f"{index} " + "x" * 100)).id)

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM folders").fetchone()[0] == len(made)
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        size = db.execute("PRAGMA page_size").fetchone()[0]
    assert pages * size <= limit
    assert folder_store.get_folder(made[0]).name == "Kept"
    for folder_id in made:  # a full store can still shrink, so it is never stuck
        folder_store.delete_folder(folder_id)
    folder_store.create_folder(NewFolder(name="Room again"))


def attempt(action: Callable[[int], object], tries: int) -> list[bool]:
    def one(index: int) -> bool:
        try:
            action(index)
        except CapacityError:
            return False
        return True

    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(one, range(tries)))


def test_folder_cap_holds_under_concurrency(db_path: Path) -> None:
    FolderStore(db_path, state()).create_folder(NewFolder(name="Seed"))
    capped = FolderStore(db_path, state(), Limits(max_folders=6))
    outcomes = attempt(lambda index: capped.create_folder(NewFolder(name=f"F{index}")), 24)
    assert sum(outcomes) == 5


def test_card_cap_holds_under_concurrency(db_path: Path) -> None:
    capped = FolderStore(db_path, state(), Limits(max_cards=5))
    folder = capped.create_folder(NewFolder(name="Race"))
    outcomes = attempt(lambda index: capped.add_card(folder.id, card(f"case-{index}")), 24)
    assert sum(outcomes) == 5
    assert len(capped.list_cards(folder.id)) == 5


def test_note_cap_holds_under_concurrency(db_path: Path) -> None:
    capped = FolderStore(db_path, state(), Limits(max_notes=5))
    folder = capped.create_folder(NewFolder(name="Race"))
    saved = capped.add_card(folder.id, card())
    outcomes = attempt(lambda _: capped.add_note(folder.id, saved.id, note()), 24)
    assert sum(outcomes) == 5


# Records: priority, timestamps, scope and privacy


def test_card_keeps_status_priority_and_reason(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Office"))
    saved = folder_store.add_card(folder.id, card())
    assert (saved.state.status, saved.state.priority) == (CardStatus.NEW, Priority.NORMAL)

    changed = CardState(
        status=CardStatus.IN_PROGRESS, priority=Priority.HIGH, reason="Hearing next week"
    )
    folder_store.update_card(folder.id, saved.id, changed)
    assert folder_store.list_cards(folder.id)[0].state == changed


def test_priority_reason_is_at_most_200_characters() -> None:
    assert len(CardState(reason="r" * 200).reason or "") == 200
    with pytest.raises(ValidationError, match="at most 200"):
        CardState(reason="r" * 201)


def test_note_keeps_date_and_confirmation(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Office"))
    saved = folder_store.add_card(folder.id, card())
    written = folder_store.add_note(folder.id, saved.id, note())
    assert written.confirmed is False

    update = NewNote(dated=date(2026, 11, 2), body="Confirmed.", confirmed=True)
    changed = folder_store.update_note(folder.id, written.id, update)
    assert (changed.dated, changed.body, changed.confirmed) == (
        date(2026, 11, 2),
        "Confirmed.",
        True,
    )


def test_timestamps_are_utc_and_child_writes_touch_the_folder(db_path: Path) -> None:
    moments = iter(datetime(2026, 10, 29, tzinfo=UTC) + timedelta(hours=n) for n in range(9))
    folder_store = FolderStore(db_path, state(), now=lambda: next(moments))
    folder = folder_store.create_folder(NewFolder(name="Clock"))
    assert folder.created_at == folder.updated_at == datetime(2026, 10, 29, tzinfo=UTC)

    saved = folder_store.add_card(folder.id, card())
    updated = folder_store.update_card(folder.id, saved.id, CardState(priority=Priority.LOW))
    assert updated.created_at == saved.created_at
    assert updated.updated_at > saved.updated_at
    assert folder_store.get_folder(folder.id).updated_at == updated.updated_at


def test_same_case_in_another_district_is_another_card(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Districts"))
    folder_store.add_card(folder.id, card())
    with pytest.raises(AlreadySavedError):
        folder_store.add_card(folder.id, card())
    folder_store.add_card(folder.id, card(district=DistrictId(chamber="senate", district=22)))
    assert len(folder_store.list_cards(folder.id)) == 2


def test_records_are_scoped_to_their_folder(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    mine = folder_store.create_folder(NewFolder(name="Mine"))
    theirs = folder_store.create_folder(NewFolder(name="Theirs"))
    saved = folder_store.add_card(mine.id, card())
    written = folder_store.add_note(mine.id, saved.id, note())

    for action in (
        lambda: folder_store.update_card(theirs.id, saved.id, CardState()),
        lambda: folder_store.delete_card(theirs.id, saved.id),
        lambda: folder_store.add_note(theirs.id, saved.id, note()),
        lambda: folder_store.update_note(theirs.id, written.id, note()),
        lambda: folder_store.delete_note(theirs.id, written.id),
    ):
        with pytest.raises(FolderNotFoundError):
            action()
    assert folder_store.list_notes(theirs.id, saved.id) == []
    assert folder_store.list_notes(mine.id, saved.id) == [written]


def test_delete_removes_children(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Gone"))
    kept = folder_store.add_card(folder.id, card("case-kept"))
    gone = folder_store.add_card(folder.id, card("case-gone"))
    deleted = folder_store.add_note(folder.id, kept.id, note())
    folder_store.add_note(folder.id, gone.id, note())

    folder_store.delete_note(folder.id, deleted.id)
    assert folder_store.list_notes(folder.id, kept.id) == []
    folder_store.delete_card(folder.id, gone.id)
    assert [c.id for c in folder_store.list_cards(folder.id)] == [kept.id]
    folder_store.delete_folder(folder.id)
    with pytest.raises(FolderNotFoundError):
        folder_store.get_folder(folder.id)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_rename_changes_only_the_name(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Old"))
    assert folder_store.rename_folder(folder.id, NewFolder(name="New")).name == "New"
    with pytest.raises(FolderNotFoundError):
        folder_store.rename_folder("missing", NewFolder(name="New"))


def test_store_keeps_no_figures() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        NewCard.model_validate({"card_key": "snap-b22003", "district": HOUSE_22, "value": 12})
    schema = (ROOT / "app/folders/schema.sql").read_text(encoding="utf-8").lower()
    for column in (" value", " moe", " cv", " estimate", " vintage", " ip ", " email"):
        assert column not in schema


@pytest.mark.parametrize(
    "text",
    [
        "Call jane@example.org",
        "Her cell 808-555-0100",
        "(808) 555-0100",
        "Call 555-0100",
        "SSN 123-45-6789",
    ],
)
def test_contact_details_are_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="individuals"):
        NewNote(dated=date(2026, 10, 29), body=text)
    with pytest.raises(ValidationError, match="individuals"):
        CardState(reason=text)
    with pytest.raises(ValidationError, match="individuals"):
        NewFolder(name=text)


def test_dated_office_text_is_not_mistaken_for_contact_details() -> None:
    assert NewNote(dated=date(2026, 10, 29), body="Met 2026-10-29 about B22003.").body


@pytest.mark.parametrize("key", ["SNAP", "a/../b", "a?b", "a#b", "a%2e", "a b", "-a", "a-", ""])
def test_bad_card_keys_are_refused(key: str) -> None:
    with pytest.raises(ValidationError, match="card_key"):
        NewCard(card_key=key, district=HOUSE_22)


@pytest.mark.parametrize("char", ["\x00", "\r", "\t", "\x7f"])
def test_control_characters_are_refused(char: str) -> None:
    with pytest.raises(ValidationError, match="control characters"):
        note(f"bad{char}byte")


def test_note_line_breaks_are_kept_and_normalized() -> None:
    assert note("one\r\ntwo").body == "one\ntwo"


@pytest.mark.parametrize("name", [1, None])
def test_text_must_be_a_string(name: object) -> None:
    with pytest.raises(ValidationError, match="string"):
        NewFolder.model_validate({"name": name})
    with pytest.raises(ValidationError, match="string"):
        NewNote.model_validate({"dated": date(2026, 10, 29), "body": name})


def test_blank_text_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        NewFolder(name="   ")


@pytest.mark.parametrize("field", ["limit", "window_seconds"])
def test_rate_hit_needs_positive_numbers(field: str) -> None:
    values = {"scope": "burst", "limit": 1, "window_seconds": 60, field: 0}
    with pytest.raises(ValidationError, match=field):
        RateHit.model_validate(values)


def test_write_failures_other_than_full_are_not_called_capacity(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder_store = FolderStore(db_path, state())
    folder_store.create_folder(NewFolder(name="Kept"))
    monkeypatch.setattr(store, "MIGRATIONS", (*store.MIGRATIONS, "BROKEN SQL;"))
    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        folder_store.create_folder(NewFolder(name="Other"))


def test_single_line_text_refuses_line_breaks() -> None:
    with pytest.raises(ValidationError, match="one line"):
        NewFolder(name="two\nlines")


def test_note_body_has_a_length_limit() -> None:
    assert len(note("n" * models.MAX_NOTE_CHARS).body) == models.MAX_NOTE_CHARS
    with pytest.raises(ValidationError, match="at most"):
        note("n" * (models.MAX_NOTE_CHARS + 1))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE cards SET status = 'bogus'",
        "UPDATE cards SET priority = 'urgent'",
        f"UPDATE cards SET reason = '{'r' * 201}'",
        "UPDATE notes SET confirmed = 2",
    ],
)
def test_schema_refuses_bad_office_state(db_path: Path, statement: str) -> None:
    folder_store = FolderStore(db_path, state())
    folder = folder_store.create_folder(NewFolder(name="Schema"))
    saved = folder_store.add_card(folder.id, card())
    folder_store.add_note(folder.id, saved.id, note())
    with sqlite3.connect(db_path) as db, pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute(statement)


# Rate buckets


def test_rate_bucket_counts_within_a_window_and_resets(db_path: Path) -> None:
    moments = iter(datetime(2026, 10, 29, 0, 0, s, tzinfo=UTC) for s in (1, 2, 3, 59))
    folder_store = FolderStore(db_path, state(), now=lambda: next(moments))
    hit = RateHit(scope="create-folder", limit=2, window_seconds=30)
    assert [folder_store.hit_rate(hit) for _ in range(4)] == [True, True, False, True]


def test_rate_bucket_survives_restart(db_path: Path) -> None:
    moment = datetime(2026, 10, 29, tzinfo=UTC)
    hit = RateHit(scope="create-folder", limit=1, window_seconds=60)
    assert FolderStore(db_path, state(), now=lambda: moment).hit_rate(hit)
    assert not FolderStore(db_path, state(), now=lambda: moment).hit_rate(hit)


def test_rate_bucket_is_atomic(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state())
    hit = RateHit(scope="burst", limit=5, window_seconds=3600)

    def one(_index: int) -> bool:
        return folder_store.hit_rate(hit)

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(one, range(24)))
    assert sum(outcomes) == 5


@pytest.mark.parametrize("scope", ["203.0.113.7", "2001:db8::1", "Jane"])
def test_rate_scope_cannot_hold_an_address_or_name(scope: str) -> None:
    with pytest.raises(ValidationError, match="scope"):
        RateHit(scope=scope, limit=1, window_seconds=60)
