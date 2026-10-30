"""Facade over the folder store (`KYD_FOLDERS_DB`), the only code that touches that file.

Every call checks the `folders` flag, opens its own short connection and, for a write, holds
one `BEGIN IMMEDIATE` transaction, so a capacity check and its insert cannot interleave with
another writer. Mirrors the read-only `app/facts.py` facade; SQLite shapes stay here.
"""

import logging
import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.features import enabled, register_feature
from app.folders.models import Card, CardState, Folder, NewCard, NewFolder, NewNote, Note, RateHit
from app.page_state import PageState
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[2]
FEATURE = "folders"
BUSY_TIMEOUT_MS = 5000
TRASH_KEEP = timedelta(days=30)
# Past the size limit, so a store at its limit can still mark records deleted.
DELETE_ROOM_PAGES = 64
# One entry per schema version, in order; each runs once, inside one transaction.
MIGRATIONS: tuple[str, ...] = (Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"),)
# A folder's live cards, in a live folder; takes the folder id as its parameter.
_LIVE_CARD_IDS = (
    "(SELECT cards.id FROM cards JOIN folders ON folders.id = cards.folder_id "
    "WHERE cards.folder_id = ? AND cards.deleted_at IS NULL AND folders.deleted_at IS NULL)"
)
log = logging.getLogger(__name__)

register_feature(FEATURE)


class FoldersDisabledError(Exception):
    """The `folders` flag is off for this request; nothing was read or written."""


class StoreConfigError(Exception):
    """The store's file is misplaced, too open, or from a newer version of the app."""


class FolderNotFoundError(Exception):
    """No such record in this folder; a record of another folder counts as missing."""


class AlreadySavedError(Exception):
    """This folder already holds a card for that key and district."""


class CapacityError(Exception):
    """A limit refused the write; the transaction rolled back and nothing changed."""


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_cards: int = 200  # per folder
    max_notes: int = 1000  # per folder, across its cards
    max_folders: int = 1000
    max_db_bytes: int = 256 * 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _checked_path(path: Path) -> Path:
    if not path.is_absolute():
        raise StoreConfigError(f"The folder store path must be absolute: {path}")
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT):
        raise StoreConfigError(f"The folder store must live outside the checkout: {resolved}")
    return resolved


def _card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        folder_id=row["folder_id"],
        card_key=row["card_key"],
        district=DistrictId(chamber=row["chamber"], district=row["district"]),
        state=CardState(status=row["status"], priority=row["priority"], reason=row["reason"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _note(row: sqlite3.Row) -> Note:
    return Note.model_validate(dict(zip(row.keys(), row, strict=True)))


def _folder(row: sqlite3.Row) -> Folder:
    return Folder.model_validate(dict(zip(row.keys(), row, strict=True)))


def _one(db: sqlite3.Connection, query: str, params: tuple[object, ...]) -> sqlite3.Row:
    # fetchall, not fetchone: a RETURNING statement left unfinished would block COMMIT.
    rows: list[sqlite3.Row] = db.execute(query, params).fetchall()
    if not rows:
        raise FolderNotFoundError("Not found in this folder")
    return rows[0]


def _count(db: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> int:
    return int(db.execute(query, params).fetchone()[0])


def _migrate(db: sqlite3.Connection) -> None:
    latest = len(MIGRATIONS)
    if _count(db, "PRAGMA user_version") == latest:
        return
    db.execute("BEGIN IMMEDIATE")
    version = _count(db, "PRAGMA user_version")  # another process may have just migrated
    if version > latest:
        raise StoreConfigError(f"The folder store is at version {version}; this app has {latest}")
    for number, script in enumerate(MIGRATIONS[version:], version + 1):
        db.executescript(script)
        db.execute(f"PRAGMA user_version = {number}")
    db.execute("COMMIT")


def _open(path: Path) -> sqlite3.Connection:
    # Native autocommit: `executescript` would otherwise commit a migration part way.
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, autocommit=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        db.execute("PRAGMA foreign_keys = ON")
        if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            db.execute("PRAGMA journal_mode = WAL")
        _migrate(db)
    except BaseException:
        db.close()
        raise
    return db


class FolderStore:
    def __init__(
        self,
        path: Path,
        state: PageState,
        limits: Limits | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.path = _checked_path(path)
        self._state = state
        self._limits = limits or Limits()
        self._now = now

    @classmethod
    def default(cls, state: PageState) -> "FolderStore":
        raw = os.environ.get("KYD_FOLDERS_DB")
        if not raw:
            raise StoreConfigError("KYD_FOLDERS_DB must name the folder store file")
        return cls(Path(raw), state)

    def _create_file(self) -> None:
        """Publish a fully migrated file in one step, so racing first opens never see it half made.

        Never open and close the live file with `os.open`: closing any descriptor of it drops
        this process's POSIX locks, which SQLite relies on.
        """
        scratch = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}")
        os.close(os.open(scratch, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
        try:
            _open(scratch).close()
            os.link(scratch, self.path)
        except FileExistsError:
            pass  # another opener published first
        finally:
            scratch.unlink(missing_ok=True)

    def _connect(self, spare_pages: int = 0) -> sqlite3.Connection:
        if not enabled(FEATURE, self._state):
            raise FoldersDisabledError
        if not self.path.exists():
            self._create_file()
        mode = stat.S_IMODE(os.lstat(self.path).st_mode)
        if mode != 0o600:
            raise StoreConfigError(f"{self.path} must have mode 0600, not {mode:04o}")
        db = _open(self.path)
        # SQLite itself then refuses growth past the cap, whichever statement causes it.
        pages = self._limits.max_db_bytes // _count(db, "PRAGMA page_size") + spare_pages
        db.execute(f"PRAGMA max_page_count = {pages}")
        return db

    @contextmanager
    def _write(self, spare_pages: int = 0) -> Generator[sqlite3.Connection]:
        """One immediate transaction. Leaving without COMMIT rolls back when the file closes."""
        start = time.perf_counter()
        try:
            with closing(self._connect(spare_pages)) as db:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_FULL:
                raise
            raise CapacityError(
                f"The folder store reached its database size limit of "
                f"{self._limits.max_db_bytes:,} bytes"
            ) from exc
        log.info("folder store write in %.1f ms", (time.perf_counter() - start) * 1000)

    def _read(self, query: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
        start = time.perf_counter()
        with closing(self._connect()) as db:
            rows: list[sqlite3.Row] = db.execute(query, params).fetchall()
        elapsed = (time.perf_counter() - start) * 1000
        log.info("folder store read: %d rows in %.1f ms", len(rows), elapsed)
        return rows

    def _stamp(self) -> str:
        return self._now().astimezone(UTC).isoformat(timespec="microseconds")

    def _touch(self, db: sqlite3.Connection, folder_id: str, stamp: str) -> None:
        query = "UPDATE folders SET updated_at = ? WHERE id = ? AND deleted_at IS NULL RETURNING id"
        _one(db, query, (stamp, folder_id))

    def _purge(self, db: sqlite3.Connection, keep: timedelta) -> None:
        cutoff = (self._now() - keep).astimezone(UTC).isoformat(timespec="microseconds")
        for table in ("notes", "cards", "folders"):  # foreign keys take the children too
            db.execute(f"DELETE FROM {table} WHERE deleted_at <= ?", (cutoff,))

    def _check_folder_room(self, db: sqlite3.Connection) -> None:
        held = _count(db, "SELECT COUNT(*) FROM folders WHERE deleted_at IS NULL")
        if held >= self._limits.max_folders:
            raise CapacityError(
                f"The folder store holds its limit of {self._limits.max_folders:,} folders"
            )

    def _check_card_room(
        self, db: sqlite3.Connection, folder_id: str, key: str, chamber: str, district: int | str
    ) -> None:
        same = (
            "SELECT COUNT(*) FROM cards WHERE folder_id = ? AND card_key = ? AND chamber = ? "
            "AND district = ? AND deleted_at IS NULL"
        )
        if _count(db, same, (folder_id, key, chamber, district)):
            raise AlreadySavedError(f"This folder already holds {key}")
        held = "SELECT COUNT(*) FROM cards WHERE folder_id = ? AND deleted_at IS NULL"
        if _count(db, held, (folder_id,)) >= self._limits.max_cards:
            raise CapacityError(f"This folder holds its limit of {self._limits.max_cards} cards")

    def _check_note_room(self, db: sqlite3.Connection, folder_id: str, adding: int = 1) -> None:
        held = _count(
            db,
            f"SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL AND card_id IN {_LIVE_CARD_IDS}",
            (folder_id,),
        )
        if held + adding > self._limits.max_notes:
            raise CapacityError(f"This folder holds its limit of {self._limits.max_notes:,} notes")

    def create_folder(self, new: NewFolder) -> Folder:
        stamp = self._stamp()
        with self._write() as db:
            self._check_folder_room(db)
            row = _one(
                db,
                "INSERT INTO folders (id, name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) RETURNING *",
                (secrets.token_urlsafe(16), new.name, stamp, stamp),
            )
        return _folder(row)

    def get_folder(self, folder_id: str) -> Folder:
        query = "SELECT * FROM folders WHERE id = ? AND deleted_at IS NULL"
        rows = self._read(query, (folder_id,))
        if not rows:
            raise FolderNotFoundError("Not found in this folder")
        return _folder(rows[0])

    def rename_folder(self, folder_id: str, new: NewFolder) -> Folder:
        with self._write() as db:
            row = _one(
                db,
                "UPDATE folders SET name = ?, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NULL RETURNING *",
                (new.name, self._stamp(), folder_id),
            )
        return _folder(row)

    def delete_folder(self, folder_id: str) -> None:
        stamp = self._stamp()
        with self._write(DELETE_ROOM_PAGES) as db:
            query = "UPDATE folders SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL "
            _one(db, query + "RETURNING id", (stamp, folder_id))
            self._purge(db, TRASH_KEEP)

    def list_deleted_folders(self) -> list[Folder]:
        rows = self._read("SELECT * FROM folders WHERE deleted_at IS NOT NULL ORDER BY id", ())
        return [_folder(row) for row in rows]

    def restore_folder(self, folder_id: str) -> Folder:
        with self._write() as db:
            self._check_folder_room(db)
            row = _one(
                db,
                "UPDATE folders SET deleted_at = NULL, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NOT NULL RETURNING *",
                (self._stamp(), folder_id),
            )
        return _folder(row)

    def add_card(self, folder_id: str, new: NewCard) -> Card:
        stamp = self._stamp()
        chamber, district = new.district.chamber, new.district.district
        state = new.state
        with self._write() as db:
            self._touch(db, folder_id, stamp)
            self._check_card_room(db, folder_id, new.card_key, chamber, district)
            row = _one(
                db,
                "INSERT INTO cards (folder_id, card_key, chamber, district, status, priority, "
                "reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
                (
                    folder_id,
                    new.card_key,
                    chamber,
                    district,
                    state.status.value,
                    state.priority.value,
                    state.reason,
                    stamp,
                    stamp,
                ),
            )
        return _card(row)

    def list_cards(self, folder_id: str) -> list[Card]:
        rows = self._read(
            f"SELECT * FROM cards WHERE id IN {_LIVE_CARD_IDS} ORDER BY id", (folder_id,)
        )
        return [_card(row) for row in rows]

    def update_card(self, folder_id: str, card_id: int, state: CardState) -> Card:
        stamp = self._stamp()
        with self._write() as db:
            self._touch(db, folder_id, stamp)
            row = _one(
                db,
                "UPDATE cards SET status = ?, priority = ?, reason = ?, updated_at = ? "
                "WHERE id = ? AND folder_id = ? AND deleted_at IS NULL RETURNING *",
                (state.status.value, state.priority.value, state.reason, stamp, card_id, folder_id),
            )
        return _card(row)

    def delete_card(self, folder_id: str, card_id: int) -> None:
        stamp = self._stamp()
        with self._write(DELETE_ROOM_PAGES) as db:
            self._touch(db, folder_id, stamp)
            _one(
                db,
                "UPDATE cards SET deleted_at = ? "
                "WHERE id = ? AND folder_id = ? AND deleted_at IS NULL RETURNING id",
                (stamp, card_id, folder_id),
            )
            self._purge(db, TRASH_KEEP)

    def list_deleted_cards(self, folder_id: str) -> list[Card]:
        query = "SELECT * FROM cards WHERE folder_id = ? AND deleted_at IS NOT NULL ORDER BY id"
        return [_card(row) for row in self._read(query, (folder_id,))]

    def restore_card(self, folder_id: str, card_id: int) -> Card:
        stamp = self._stamp()
        with self._write() as db:
            self._touch(db, folder_id, stamp)
            gone = _one(
                db,
                "SELECT card_key, chamber, district FROM cards "
                "WHERE id = ? AND folder_id = ? AND deleted_at IS NOT NULL",
                (card_id, folder_id),
            )
            self._check_card_room(db, folder_id, *gone)
            query = "SELECT COUNT(*) FROM notes WHERE card_id = ? AND deleted_at IS NULL"
            self._check_note_room(db, folder_id, _count(db, query, (card_id,)))
            row = _one(
                db,
                "UPDATE cards SET deleted_at = NULL, updated_at = ? WHERE id = ? RETURNING *",
                (stamp, card_id),
            )
        return _card(row)

    def add_note(self, folder_id: str, card_id: int, new: NewNote) -> Note:
        stamp = self._stamp()
        with self._write() as db:
            self._touch(db, folder_id, stamp)
            live = f"SELECT id FROM cards WHERE id = ? AND id IN {_LIVE_CARD_IDS}"
            _one(db, live, (card_id, folder_id))
            self._check_note_room(db, folder_id)
            row = _one(
                db,
                "INSERT INTO notes (card_id, dated, body, confirmed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) RETURNING *",
                (card_id, new.dated.isoformat(), new.body, int(new.confirmed), stamp, stamp),
            )
        return _note(row)

    def list_notes(self, folder_id: str, card_id: int) -> list[Note]:
        rows = self._read(
            f"SELECT * FROM notes WHERE card_id = ? AND deleted_at IS NULL "
            f"AND card_id IN {_LIVE_CARD_IDS} ORDER BY dated, id",
            (card_id, folder_id),
        )
        return [_note(row) for row in rows]

    def update_note(self, folder_id: str, note_id: int, new: NewNote) -> Note:
        stamp = self._stamp()
        with self._write() as db:
            self._touch(db, folder_id, stamp)
            row = _one(
                db,
                f"UPDATE notes SET dated = ?, body = ?, confirmed = ?, updated_at = ? "
                f"WHERE id = ? AND deleted_at IS NULL AND card_id IN {_LIVE_CARD_IDS} RETURNING *",
                (new.dated.isoformat(), new.body, int(new.confirmed), stamp, note_id, folder_id),
            )
        return _note(row)

    def delete_note(self, folder_id: str, note_id: int) -> None:
        stamp = self._stamp()
        with self._write(DELETE_ROOM_PAGES) as db:
            self._touch(db, folder_id, stamp)
            _one(
                db,
                f"UPDATE notes SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL "
                f"AND card_id IN {_LIVE_CARD_IDS} RETURNING id",
                (stamp, note_id, folder_id),
            )
            self._purge(db, TRASH_KEEP)

    def list_deleted_notes(self, folder_id: str) -> list[Note]:
        rows = self._read(
            "SELECT * FROM notes WHERE deleted_at IS NOT NULL "
            "AND card_id IN (SELECT id FROM cards WHERE folder_id = ?) ORDER BY id",
            (folder_id,),
        )
        return [_note(row) for row in rows]

    def restore_note(self, folder_id: str, note_id: int) -> Note:
        stamp = self._stamp()
        with self._write() as db:
            self._touch(db, folder_id, stamp)
            live_card = f"deleted_at IS NOT NULL AND card_id IN {_LIVE_CARD_IDS}"
            _one(db, f"SELECT id FROM notes WHERE id = ? AND {live_card}", (note_id, folder_id))
            self._check_note_room(db, folder_id)
            row = _one(
                db,
                "UPDATE notes SET deleted_at = NULL, updated_at = ? WHERE id = ? RETURNING *",
                (stamp, note_id),
            )
        return _note(row)

    def purge_deleted(self, keep: timedelta = TRASH_KEEP) -> None:
        """Remove for good whatever has been in the trash longer than `keep`."""
        with self._write() as db:
            self._purge(db, keep)

    def hit_rate(self, hit: RateHit) -> bool:
        """Count one hit in the current window; False when the window is already at its limit."""
        window = int(self._now().timestamp()) // hit.window_seconds
        with self._write() as db:
            rows: list[sqlite3.Row] = db.execute(
                "SELECT window_start, hits FROM rate_buckets WHERE scope = ?", (hit.scope,)
            ).fetchall()
            hits: int = rows[0]["hits"] if rows and rows[0]["window_start"] == window else 0
            if hits >= hit.limit:
                return False
            db.execute(
                "INSERT OR REPLACE INTO rate_buckets (scope, window_start, hits) VALUES (?, ?, ?)",
                (hit.scope, window, hits + 1),
            )
        return True
