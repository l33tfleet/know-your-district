"""Facade over the folder store, the only code that touches that file.

The file is `KYD_FOLDERS_DB` when set, else `default_path()`, always outside the checkout.

Every call checks the `folders` flag and opens its own short connection, which creates or
upgrades the file in one transaction. Mirrors the read-only `app/facts.py` facade; SQLite shapes
stay here.
"""

import logging
import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    validate_call,
)

from app.features import enabled, register_feature
from app.page_state import PageState
from etl.boundaries import Chamber

ROOT = Path(__file__).resolve().parents[2]
FEATURE = "folders"
BUSY_TIMEOUT_MS = 5000
# One entry per schema version, in order; each runs once, inside one transaction.
MIGRATIONS: tuple[str, ...] = (Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"),)
LIVE_FOLDER = "SELECT id, name FROM folders WHERE id = ? AND deleted_at IS NULL"
LIVE_CARDS = (
    "SELECT id, card_key AS case_id, chamber, district, priority, reason, status FROM cards"
    " WHERE folder_id = ? AND deleted_at IS NULL ORDER BY id"
)
log = logging.getLogger(__name__)

register_feature(FEATURE)

FolderId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
FolderName = Annotated[str, StringConstraints(min_length=1, max_length=120)]
CaseId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
CardId = Annotated[int, Field(ge=1)]
District = Annotated[int, Field(ge=1)]
Priority = Literal["high", "normal", "low"]
Status = Literal["idea", "contacted", "planned", "done"]
# No control characters or line separators, so a reason stays one line on the page. They are
# checked before spaces are trimmed: trimming would remove them from the ends unseen.
Reason = Annotated[
    str,
    StringConstraints(pattern=r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029]*$"),
    AfterValidator(str.strip),
    StringConstraints(min_length=1, max_length=200),
]


class FoldersDisabledError(Exception):
    """The `folders` flag is off for this request; nothing was read or written."""


class StoreConfigError(Exception):
    """The store's file is misplaced, too open, or from a newer version of the app."""


class CapacityError(Exception):
    """A limit refused the write; the transaction rolled back and nothing changed."""


class FolderNotFoundError(Exception):
    """No live folder has this id, or no live card of that folder has this card id."""


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_db_bytes: int = 256 * 1024 * 1024


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    case_id: str
    chamber: Chamber
    district: int
    priority: Priority
    reason: str | None
    status: Status


class Folder(BaseModel):
    """Keys and office state; figures are re-read from the fact table on every render."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    cards: tuple[Card, ...]


def new_folder_id() -> str:
    return secrets.token_hex(16)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _checked_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT):
        raise StoreConfigError(f"The folder store must live outside the checkout: {resolved}")
    return resolved


def default_path() -> Path:
    """The XDG state location; makes its own directory and no other, never in the checkout."""
    state_home = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    path = _checked_path(Path(state_home) / "know-your-district/folders.db")
    try:
        path.parent.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise StoreConfigError(f"Cannot make the folder store's directory: {exc}") from exc
    return path


def _count(db: sqlite3.Connection, query: str) -> int:
    return int(db.execute(query).fetchone()[0])


def _require_ceiling(db: sqlite3.Connection, max_bytes: int) -> None:
    """Set the cap inside the transaction; SQLite answers with the limit it really applied."""
    pages = max_bytes // _count(db, "PRAGMA page_size")
    effective = _count(db, f"PRAGMA max_page_count = {pages}")
    if effective != pages:
        raise CapacityError(
            f"The folder store cannot enforce its database size limit of {max_bytes:,} bytes: "
            f"SQLite applied {effective:,} pages, not {pages:,}"
        )


def _migrate(db: sqlite3.Connection, max_bytes: int) -> None:
    latest = len(MIGRATIONS)
    if _count(db, "PRAGMA user_version") == latest:
        return
    db.execute("BEGIN IMMEDIATE")
    version = _count(db, "PRAGMA user_version")  # another process may have just migrated
    if version > latest:
        raise StoreConfigError(f"The folder store is at version {version}; this app has {latest}")
    _require_ceiling(db, max_bytes)  # a migration is a write: SQLite then refuses growth past it
    for number, script in enumerate(MIGRATIONS[version:], version + 1):
        db.executescript(script)
        db.execute(f"PRAGMA user_version = {number}")
    db.execute("COMMIT")


def _require_folder(db: sqlite3.Connection, folder_id: str) -> None:
    if db.execute(LIVE_FOLDER, (folder_id,)).fetchone() is None:
        raise FolderNotFoundError(folder_id)


def _insert_card(
    db: sqlite3.Connection, folder_id: str, case_id: str, chamber: str, district: int
) -> None:
    stamp = now()
    db.execute(
        "INSERT INTO cards (folder_id, card_key, chamber, district, status, priority,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, 'idea', 'normal', ?, ?)"
        " ON CONFLICT (folder_id, card_key, chamber, district) WHERE deleted_at IS NULL"
        " DO NOTHING",
        (folder_id, case_id, chamber, district, stamp, stamp),
    )


def _update_card(
    db: sqlite3.Connection, folder_id: str, card_id: int, assignment: str, *values: str
) -> None:
    """Change a live card of a live folder; the folder id scopes every write."""
    _require_folder(db, folder_id)
    changed = db.execute(
        f"UPDATE cards SET {assignment}, updated_at = ?"
        " WHERE id = ? AND folder_id = ? AND deleted_at IS NULL",
        (*values, now(), card_id, folder_id),
    )
    if changed.rowcount != 1:
        raise FolderNotFoundError(folder_id)


def _open(path: Path, max_bytes: int) -> sqlite3.Connection:
    # Native autocommit: `executescript` would otherwise commit a migration part way.
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, autocommit=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        db.execute("PRAGMA foreign_keys = ON")
        if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            db.execute("PRAGMA journal_mode = WAL")
        _migrate(db, max_bytes)
    except BaseException:
        db.close()
        raise
    return db


class FolderStore:
    def __init__(self, path: Path, state: PageState, limits: Limits | None = None) -> None:
        self.path = _checked_path(path)
        self._state = state
        self._limits = limits or Limits()

    def _create_file(self) -> None:
        """Publish a fully migrated file in one step, so no opener ever sees it half made.

        Never open and close the live file with `os.open`: closing any descriptor of it drops
        this process's POSIX locks, which SQLite relies on.
        """
        scratch = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}")
        try:
            os.close(os.open(scratch, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
        except OSError as exc:
            raise StoreConfigError(f"Cannot make the folder store's file: {exc}") from exc
        try:
            _open(scratch, self._limits.max_db_bytes).close()
            os.link(scratch, self.path)
        finally:
            scratch.unlink(missing_ok=True)

    def _connect(self) -> sqlite3.Connection:
        if not enabled(FEATURE, self._state):
            raise FoldersDisabledError
        if not self.path.exists():
            self._create_file()
        mode = stat.S_IMODE(os.lstat(self.path).st_mode)
        if mode != 0o600:
            raise StoreConfigError(f"{self.path} must have mode 0600, not {mode:04o}")
        return _open(self.path, self._limits.max_db_bytes)

    @contextmanager
    def _capacity(self) -> Generator[None]:
        try:
            yield
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_FULL:
                raise
            raise CapacityError(
                f"The folder store reached its database size limit of "
                f"{self._limits.max_db_bytes:,} bytes"
            ) from exc

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        """One short transaction under the size ceiling; closing rolls back an unfinished one."""
        with self._capacity(), closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            _require_ceiling(db, self._limits.max_db_bytes)
            yield db
            db.execute("COMMIT")

    def initialize(self) -> None:
        """Create or upgrade the file; refused, it leaves the file as it was."""
        start = time.perf_counter()
        with self._capacity():
            self._connect().close()
        log.info("folder store ready in %.1f ms", (time.perf_counter() - start) * 1000)

    @validate_call
    def create_folder(
        self, name: FolderName, case_id: CaseId, chamber: Chamber, district: District
    ) -> str:
        """A folder and its first case in one transaction: a folder's district is its cards'."""
        folder_id = new_folder_id()
        with self._write() as db:
            stamp = now()
            db.execute(
                "INSERT INTO folders (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (folder_id, name, stamp, stamp),
            )
            _insert_card(db, folder_id, case_id, chamber, district)
        return folder_id

    @validate_call
    def save_case(
        self, folder_id: FolderId, case_id: CaseId, chamber: Chamber, district: District
    ) -> None:
        """Add a case by its id and district; saving it again keeps the card as it is."""
        with self._write() as db:
            _require_folder(db, folder_id)
            _insert_card(db, folder_id, case_id, chamber, district)

    @validate_call
    def set_priority(
        self, folder_id: FolderId, card_id: CardId, priority: Priority, reason: Reason
    ) -> None:
        with self._write() as db:
            _update_card(db, folder_id, card_id, "priority = ?, reason = ?", priority, reason)

    @validate_call
    def set_status(self, folder_id: FolderId, card_id: CardId, status: Status) -> None:
        with self._write() as db:
            _update_card(db, folder_id, card_id, "status = ?", status)

    @validate_call
    def get_folder(self, folder_id: FolderId) -> Folder:
        with closing(self._connect()) as db:
            row = db.execute(LIVE_FOLDER, (folder_id,)).fetchone()
            if row is None:
                raise FolderNotFoundError(folder_id)
            cards = db.execute(LIVE_CARDS, (folder_id,)).fetchall()
        return Folder(id=row["id"], name=row["name"], cards=tuple(Card(**dict(c)) for c in cards))
