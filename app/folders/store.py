"""Facade over the folder store (`KYD_FOLDERS_DB`), the only code that touches that file.

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
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.features import enabled, register_feature
from app.page_state import PageState

ROOT = Path(__file__).resolve().parents[2]
FEATURE = "folders"
BUSY_TIMEOUT_MS = 5000
# One entry per schema version, in order; each runs once, inside one transaction.
MIGRATIONS: tuple[str, ...] = (Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"),)
log = logging.getLogger(__name__)

register_feature(FEATURE)


class FoldersDisabledError(Exception):
    """The `folders` flag is off for this request; nothing was read or written."""


class StoreConfigError(Exception):
    """The store's file is misplaced, too open, or from a newer version of the app."""


class CapacityError(Exception):
    """A limit refused the write; the transaction rolled back and nothing changed."""


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_db_bytes: int = 256 * 1024 * 1024


def _checked_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT):
        raise StoreConfigError(f"The folder store must live outside the checkout: {resolved}")
    return resolved


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
        os.close(os.open(scratch, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
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

    def initialize(self) -> None:
        """Create or upgrade the file; refused, it leaves the file as it was."""
        start = time.perf_counter()
        try:
            self._connect().close()
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_FULL:
                raise
            raise CapacityError(
                f"The folder store reached its database size limit of "
                f"{self._limits.max_db_bytes:,} bytes"
            ) from exc
        log.info("folder store ready in %.1f ms", (time.perf_counter() - start) * 1000)
