"""#224, first slice of #153: the one writable store, before any record type.

The file is outside the checkout, 0600, WAL and busy-timed, and the flag guards it. Setup is
transactional, repeats safely, and validates the ceiling SQLite really enforces before migrating.
"""

import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest

from app import features
from app.folders import store
from app.page_state import PageState, page_state

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 128 * 1024
VERSION = "PRAGMA user_version"
FOLDERS = "SELECT COUNT(*) FROM folders"
INSERT_FOLDER = "INSERT INTO folders VALUES (?, 'Kalihi outreach', 't', 't', NULL)"


def state() -> PageState:
    result = page_state("house", "22")
    assert result is not None
    return result


def set_flag(path: Path, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    config = path / "features.toml"
    config.write_text(f'folders = "{status}"\n' if status else "", encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", config)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    set_flag(tmp_path, monkeypatch, "on")
    return tmp_path / "folders.db"


def capped(path: Path, limit: int = LIMIT) -> store.FolderStore:
    return store.FolderStore(path, state(), store.Limits(max_db_bytes=limit))


def scalar(path: Path, query: str) -> int:
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute(query).fetchone()[0])


def has_table(path: Path, name: str) -> bool:
    return bool(scalar(path, f"SELECT COUNT(*) FROM sqlite_master WHERE name = '{name}'"))


def db_bytes(path: Path) -> int:
    return scalar(path, "PRAGMA page_count") * scalar(path, "PRAGMA page_size")


def add_folders(path: Path, ids: range) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany(INSERT_FOLDER, [(f"folder-{n}",) for n in ids])


def add_migration(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    monkeypatch.setattr(store, "MIGRATIONS", (*store.MIGRATIONS, script))


def test_migrations_repeat_safely_and_records_survive_restart(db_path: Path) -> None:
    for number in range(3):
        capped(db_path).initialize()
        add_folders(db_path, range(number, number + 1))
    assert scalar(db_path, VERSION) == len(store.MIGRATIONS)
    assert scalar(db_path, FOLDERS) == 3
    assert all(has_table(db_path, name) for name in ("cards", "notes", "rate_buckets"))


def test_newer_database_is_refused(db_path: Path) -> None:
    capped(db_path).initialize()
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(store.StoreConfigError, match="version 99"):
        capped(db_path).initialize()


def test_write_failures_other_than_full_are_not_called_capacity(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capped(db_path).initialize()
    add_migration(monkeypatch, "BROKEN SQL;")
    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        capped(db_path).initialize()


def test_file_is_private_wal_and_busy_timed(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "BUSY_TIMEOUT_MS", 1234)  # sqlite3.connect defaults to 5000
    folder_store = capped(db_path)
    folder_store.initialize()
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600

    with closing(folder_store._connect()) as db:  # pyright: ignore[reportPrivateUsage] -- pins the connection's pragmas
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO rate_buckets VALUES ('sidecar', 0, 0)")
        for sidecar in ("-wal", "-shm"):
            assert stat.S_IMODE(Path(f"{db_path}{sidecar}").stat().st_mode) == 0o600


def test_loose_file_mode_is_refused(db_path: Path) -> None:
    db_path.touch()
    db_path.chmod(0o644)
    with pytest.raises(store.StoreConfigError, match="0600"):
        capped(db_path).initialize()


def test_file_in_checkout_is_refused(db_path: Path) -> None:
    with pytest.raises(store.StoreConfigError, match="outside the checkout"):
        capped(ROOT / "data" / "folders.db")


@pytest.mark.parametrize("status", ["", "off"])
def test_flag_off_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    set_flag(tmp_path, monkeypatch, status)
    with pytest.raises(store.FoldersDisabledError):
        capped(tmp_path / "folders.db").initialize()
    assert not (tmp_path / "folders.db").exists()


@pytest.mark.parametrize("limit", [1000, 4096 * 2**33], ids=["under-a-page", "past-sqlite-max"])
def test_ceiling_sqlite_cannot_enforce_is_refused(db_path: Path, limit: int) -> None:
    with pytest.raises(store.CapacityError, match="cannot enforce"):
        capped(db_path, limit).initialize()
    assert list(db_path.parent.glob("*folders.db*")) == []
