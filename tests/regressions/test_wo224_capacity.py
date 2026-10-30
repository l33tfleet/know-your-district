"""#224 decision of 2026-10-30: the size limit is a true ceiling, and a full store stays usable.

Room for deletes sits inside `max_db_bytes`, not above it. A write refused by the limit changes
nothing, and a limit SQLite cannot enforce on the file refuses writes instead of being ignored.
"""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import features
from app.folders import store
from app.folders.models import NewCard, NewFolder, NewNote
from app.folders.store import CapacityError, FolderStore, Limits
from app.page_state import PageState, page_state
from etl.boundaries import DistrictId

LIMIT = 128 * 1024
LONG_NAME = "outreach " * 13
COUNTED = ("folders", "cards", "notes")
STAMP = "2026-10-29T00:00:00+00:00"


def state() -> PageState:
    result = page_state("house", "22")
    assert result is not None
    return result


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "features.toml"
    config.write_text('folders = "on"\n', encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", config)
    return tmp_path / "folders.db"


def capped(path: Path, limit: int = LIMIT) -> FolderStore:
    return FolderStore(path, state(), Limits(max_db_bytes=limit))


def db_bytes(path: Path) -> int:
    with closing(sqlite3.connect(path)) as db:
        pages = int(db.execute("PRAGMA page_count").fetchone()[0])
        return pages * int(db.execute("PRAGMA page_size").fetchone()[0])


def rows(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as db:
        return {t: int(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in COUNTED}


def fill_with_folders(folder_store: FolderStore) -> list[str]:
    made: list[str] = []
    with pytest.raises(CapacityError, match="database size"):
        for _ in range(5000):
            made.append(folder_store.create_folder(NewFolder(name=LONG_NAME)).id)
    return made


def add_card(folder_store: FolderStore, folder_id: str, key: str = "snap-b22003") -> int:
    new = NewCard(card_key=key, district=DistrictId(chamber="house", district=22))
    return folder_store.add_card(folder_id, new).id


def note() -> NewNote:
    return NewNote(dated=date(2026, 10, 29), body="Asked the agency about hours.")


def test_ceiling_holds_through_fill_delete_purge_and_reopen(db_path: Path) -> None:
    folder_store = capped(db_path)
    made = fill_with_folders(folder_store)
    full = rows(db_path)
    assert full["folders"] == len(made)
    assert db_bytes(db_path) <= LIMIT

    with pytest.raises(CapacityError, match="database size"):
        folder_store.create_folder(NewFolder(name=LONG_NAME))
    assert rows(db_path) == full

    for folder_id in made:
        folder_store.delete_folder(folder_id)
        assert db_bytes(db_path) <= LIMIT
    assert len(folder_store.list_deleted_folders()) == len(made)

    # The trash still holds its space, so nothing new fits before the purge.
    with pytest.raises(CapacityError, match="database size"):
        folder_store.create_folder(NewFolder(name=LONG_NAME))
    assert rows(db_path) == full
    assert db_bytes(db_path) <= LIMIT

    folder_store.purge_deleted(timedelta(0))
    assert rows(db_path)["folders"] == 0
    assert db_bytes(db_path) <= LIMIT

    kept = folder_store.create_folder(NewFolder(name=LONG_NAME))
    assert db_bytes(db_path) <= LIMIT

    reopened = capped(db_path)
    assert reopened.get_folder(kept.id).name == kept.name
    refill = fill_with_folders(reopened)
    assert len(refill) > 1
    assert db_bytes(db_path) <= LIMIT


def test_cards_and_notes_can_be_deleted_at_capacity(db_path: Path) -> None:
    full = FolderStore(db_path, state(), Limits(max_db_bytes=LIMIT, max_notes=100_000))
    folder_id = full.create_folder(NewFolder(name="Kalihi outreach")).id
    card_id = add_card(full, folder_id)
    first = full.add_note(folder_id, card_id, note())
    with pytest.raises(CapacityError, match="database size"):
        for _ in range(5000):
            full.add_note(folder_id, card_id, note())
    before = rows(db_path)
    with pytest.raises(CapacityError, match="database size"):
        full.add_note(folder_id, card_id, note())
    assert rows(db_path) == before

    full.delete_note(folder_id, first.id)
    assert db_bytes(db_path) <= LIMIT
    full.delete_card(folder_id, card_id)
    assert db_bytes(db_path) <= LIMIT
    assert {n.id for n in full.list_deleted_notes(folder_id)} == {first.id}
    assert full.list_cards(folder_id) == []


def test_ordinary_writes_stop_short_of_the_room_kept_for_deletes(db_path: Path) -> None:
    fill_with_folders(capped(db_path))
    assert db_bytes(db_path) <= LIMIT - LIMIT // store.DELETE_RESERVE_DIVISOR


def test_a_write_that_only_changes_a_row_is_refused_inside_the_reserve(db_path: Path) -> None:
    folder_store = capped(db_path)
    made = fill_with_folders(folder_store)
    for folder_id in made[1:]:  # soft deletes spend the reserve
        folder_store.delete_folder(folder_id)
    assert db_bytes(db_path) > LIMIT - LIMIT // store.DELETE_RESERVE_DIVISOR

    before = folder_store.get_folder(made[0])
    with pytest.raises(CapacityError, match="database size"):
        folder_store.rename_folder(made[0], NewFolder(name="Hilo outreach"))
    assert folder_store.get_folder(made[0]) == before


def test_limit_below_the_file_refuses_writes_and_keeps_reads(db_path: Path) -> None:
    roomy = capped(db_path, 2 * LIMIT)
    made = fill_with_folders(roomy)
    assert db_bytes(db_path) > LIMIT
    before = rows(db_path)

    small = capped(db_path)
    for write in (
        lambda: small.create_folder(NewFolder(name="Hilo outreach")),
        lambda: small.delete_folder(made[0]),
        lambda: small.purge_deleted(timedelta(0)),
    ):
        with pytest.raises(CapacityError, match="cannot enforce"):
            write()
    assert rows(db_path) == before
    assert small.get_folder(made[0]).name == LONG_NAME.strip()


def test_delete_past_the_reserve_is_refused_whole(db_path: Path) -> None:
    folder_store = FolderStore(db_path, state(), Limits(max_db_bytes=LIMIT, max_notes=100_000))
    folder_id = folder_store.create_folder(NewFolder(name="Kalihi outreach")).id
    card_id = add_card(folder_store, folder_id)
    pages = LIMIT // 4096
    with closing(sqlite3.connect(db_path)) as db:
        db.execute(f"PRAGMA max_page_count = {pages}")
        with pytest.raises(sqlite3.OperationalError, match="full"):
            for _ in range(20_000):
                db.execute(
                    "INSERT INTO notes (card_id, dated, body, confirmed, created_at, updated_at) "
                    "VALUES (?, '2026-10-29', 'n', 0, ?, ?)",
                    (card_id, STAMP, STAMP),
                )
                db.commit()
    assert db_bytes(db_path) == LIMIT

    ids = [n.id for n in folder_store.list_notes(folder_id, card_id)]
    done = 0
    with pytest.raises(CapacityError, match="database size"):
        for note_id in ids:
            folder_store.delete_note(folder_id, note_id)
            done += 1
    assert len(folder_store.list_deleted_notes(folder_id)) == done
    assert db_bytes(db_path) == LIMIT

    folder_store.purge_deleted(timedelta(0))
    assert folder_store.list_deleted_notes(folder_id) == []


def test_migration_past_the_ceiling_rolls_back_as_a_capacity_refusal(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder_store = capped(db_path)
    folder = folder_store.create_folder(NewFolder(name="Kalihi outreach"))
    bulky = "CREATE TABLE bulky (body BLOB); INSERT INTO bulky VALUES (zeroblob(1048576));"
    monkeypatch.setattr(store, "MIGRATIONS", (*store.MIGRATIONS, bulky))

    with pytest.raises(CapacityError, match="database size"):
        folder_store.get_folder(folder.id)

    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name = 'bulky'").fetchall() == []
    assert db_bytes(db_path) <= LIMIT


def oversized_with_free_pages(path: Path) -> tuple[FolderStore, str]:
    """A file past `LIMIT` whose free pages could hold a migration; one folder stays live."""
    roomy = capped(path, 2 * LIMIT)
    keep, *rest = fill_with_folders(roomy)
    for folder_id in rest:
        roomy.delete_folder(folder_id)
    roomy.purge_deleted(timedelta(0))
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA freelist_count").fetchone()[0] > 8
    assert db_bytes(path) > LIMIT
    return roomy, keep


def test_pending_migration_cannot_spend_free_pages_past_the_ceiling(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roomy, keep = oversized_with_free_pages(db_path)
    before, size = rows(db_path), db_bytes(db_path)
    monkeypatch.setattr(
        store, "MIGRATIONS", (*store.MIGRATIONS, "CREATE TABLE small (id INTEGER);")
    )

    with pytest.raises(CapacityError, match="cannot enforce"):
        capped(db_path).get_folder(keep)

    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name = 'small'").fetchall() == []
    assert rows(db_path) == before
    assert db_bytes(db_path) == size

    # Refused, not stuck: a limit that fits the file lets the same migration through.
    assert roomy.get_folder(keep).id == keep
    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_read_that_loses_the_migration_race_is_not_refused(db_path: Path) -> None:
    _, keep = oversized_with_free_pages(db_path)
    with closing(sqlite3.connect(db_path, autocommit=True)) as winner:
        winner.execute("PRAGMA user_version = 0")
        winner.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(1) as pool:
            loser = pool.submit(capped(db_path).get_folder, keep)
            time.sleep(0.5)  # the reader saw version 0 and now waits behind the winner
            winner.execute("PRAGMA user_version = 1")
            winner.execute("COMMIT")
            assert loser.result().id == keep


def test_ceiling_holds_under_concurrent_writers(db_path: Path) -> None:
    folder_store = capped(db_path)

    def one(_index: int) -> bool:
        try:
            folder_store.create_folder(NewFolder(name=LONG_NAME))
        except CapacityError:
            return False
        return True

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(one, range(600)))
    assert not all(outcomes)
    assert rows(db_path)["folders"] == sum(outcomes)
    assert db_bytes(db_path) <= LIMIT - LIMIT // store.DELETE_RESERVE_DIVISOR
