"""Facade over the folder store, the only code that touches that file.

The file is `KYD_FOLDERS_DB` when set, else `default_path()`, always outside the checkout.

Every call checks the `folders` flag and opens its own short connection, which creates or
upgrades the file in one transaction. Mirrors the read-only `app/facts.py` facade; SQLite shapes
stay here.

The folder link is the credential: errors and reprs never carry a folder id or a note, and text
that holds personal details is refused here, whichever caller wrote it. A folder's last write
sets when it expires (`app/folders/retention.py`).
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
from app.folders import pii
from app.folders.retention import Purged, expiry_cutoff
from app.page_state import PageState
from etl.boundaries import Chamber

ROOT = Path(__file__).resolve().parents[2]
FEATURE = "folders"
DEMO_ID = "de000000000000000000000000000233"
BUSY_TIMEOUT_MS = 5000
# One entry per schema version, in order; each runs once, inside one transaction.
MIGRATIONS: tuple[str, ...] = (Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"),)
LIVE_FOLDER = "SELECT id, name FROM folders WHERE id = ? AND deleted_at IS NULL AND updated_at > ?"
LIVE_CARDS = (
    "SELECT id, card_key AS case_id, chamber, district, priority, reason, status,"
    " created_at, updated_at FROM cards"
    " WHERE folder_id = ? AND deleted_at IS NULL ORDER BY id"
)
LIVE_NOTES = (
    "SELECT notes.id, notes.card_id, notes.dated, notes.body FROM notes"
    " JOIN cards ON cards.id = notes.card_id"
    " WHERE cards.folder_id = ? AND cards.deleted_at IS NULL AND notes.deleted_at IS NULL"
    " ORDER BY notes.id"
)
RATE_BUCKET_TTL_SECONDS = 24 * 60 * 60  # no rule's window may be longer
log = logging.getLogger(__name__)

register_feature(FEATURE)
# Refused input never appears in the error, where a log or error report could keep it.
checked = validate_call(config=ConfigDict(hide_input_in_errors=True))


def _no_personal_details(text: str) -> str:
    if pii.find(text):
        raise ValueError("Personal phone numbers, emails and addresses are not kept here.")
    return text


def _not_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("A note needs words.")
    return text


FolderId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
FolderName = Annotated[
    str, StringConstraints(min_length=1, max_length=120), AfterValidator(_no_personal_details)
]
CaseId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
CardId = Annotated[int, Field(ge=1)]
NoteId = Annotated[int, Field(ge=1)]
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
    AfterValidator(_no_personal_details),
]
# Kept exactly as submitted, line breaks and spaces included: a confirmation covers these words.
NoteText = Annotated[
    str,
    StringConstraints(
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029]*$", max_length=1000
    ),
    AfterValidator(_not_blank),
]
NoteBody = Annotated[NoteText, AfterValidator(_no_personal_details)]


class FoldersDisabledError(Exception):
    """The `folders` flag is off for this request; nothing was read or written."""


class StoreConfigError(Exception):
    """The store's file is misplaced, too open, or from a newer version of the app."""


class CapacityError(Exception):
    """A limit refused the write; the transaction rolled back and nothing changed."""


class FolderNotFoundError(Exception):
    """No live folder has this id, or no live card of that folder has this card id."""


class RateLimitedError(Exception):
    """A request limit refused the call; no counter moved."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Try again in {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class RateRule(BaseModel):
    """At most `limit` hits per `window_seconds` for one scope; a scope never holds a raw IP."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: str
    limit: Annotated[int, Field(ge=1)]
    window_seconds: Annotated[int, Field(ge=1, le=RATE_BUCKET_TTL_SECONDS)]


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
    created_at: str
    updated_at: str


class Folder(BaseModel):
    """Keys and office state; figures are re-read from the fact table on every render."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(repr=False)
    name: str
    cards: tuple[Card, ...]


class Note(BaseModel):
    """Office words: read only through `list_notes`, so no folder read carries them onward."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    card_id: int
    dated: str
    body: str = Field(repr=False)


class DemoCard(BaseModel):
    """Validated office state for one catalog case; no observations or private residents."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: CaseId
    priority: Priority
    status: Status
    body: NoteBody
    dated: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class VisitorWrite(BaseModel):
    model_config = ConfigDict(frozen=True)
    folder_id: str = Field(repr=False)
    cards: dict[int, int] = Field(default_factory=dict[int, int])
    notes: dict[int, int] = Field(default_factory=dict[int, int])

    def card(self, original: int) -> int:
        if self.cards and original not in self.cards:
            raise FolderNotFoundError
        return self.cards.get(original, original)

    def note(self, original: int) -> int:
        if self.cards and original not in self.notes:
            raise FolderNotFoundError
        return self.notes.get(original, original)


def _require_mutable(db: sqlite3.Connection, folder_id: str) -> None:
    if folder_id == DEMO_ID:
        raise FolderNotFoundError
    _require_folder(db, folder_id)


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


def _require_folder(db: sqlite3.Connection, folder_id: str) -> sqlite3.Row:
    row = db.execute(LIVE_FOLDER, (folder_id, expiry_cutoff(now()))).fetchone()
    if row is None:
        raise FolderNotFoundError
    return row


def _touch(db: sqlite3.Connection, folder_id: str) -> None:
    """Every write to a folder's contents restarts its retention clock."""
    db.execute("UPDATE folders SET updated_at = ? WHERE id = ?", (now(), folder_id))


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
    db: sqlite3.Connection, folder_id: str, card_id: int, assignment: str, *values: str | None
) -> None:
    """Change a live card of a live folder; the folder id scopes every write."""
    _require_mutable(db, folder_id)
    changed = db.execute(
        f"UPDATE cards SET {assignment}, updated_at = ?"
        " WHERE id = ? AND folder_id = ? AND deleted_at IS NULL",
        (*values, now(), card_id, folder_id),
    )
    if changed.rowcount != 1:
        raise FolderNotFoundError
    _touch(db, folder_id)


def _open(path: Path, max_bytes: int) -> sqlite3.Connection:
    # Native autocommit: `executescript` would otherwise commit a migration part way.
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, autocommit=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA secure_delete = ON")  # removed notes leave no bytes in free pages
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
        self._transaction: sqlite3.Connection | None = None

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
        if self._transaction is not None:
            yield self._transaction
            return
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

    @checked
    def refresh_demo(self, cards: tuple[DemoCard, ...]) -> None:
        """Replace only the reserved seed atomically; ordinary folders retain their identities."""
        with self._write() as db:
            db.execute("DELETE FROM folders WHERE id = ?", (DEMO_ID,))
            stamp = now()
            db.execute(
                "INSERT INTO folders (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (DEMO_ID, "Hawaiʻi outreach demo", stamp, stamp),
            )
            for card in cards:
                _insert_card(db, DEMO_ID, card.case_id, "house", 22)
                db.execute(
                    "UPDATE cards SET priority = ?, status = ?, created_at = ?, updated_at = ?"
                    " WHERE folder_id = ? AND card_key = ?",
                    (card.priority, card.status, card.dated, card.dated, DEMO_ID, card.case_id),
                )
                db.execute(
                    "INSERT INTO notes (card_id, dated, body, confirmed, created_at, updated_at)"
                    " SELECT id, ?, ?, 1, ?, ? FROM cards WHERE folder_id = ? AND card_key = ?",
                    (card.dated, card.body, stamp, stamp, DEMO_ID, card.case_id),
                )

    @contextmanager
    def visitor_write(self, folder_id: str) -> Generator[VisitorWrite]:
        """Request-local transaction: remap seed identities and roll back copy/edit on failure."""
        if folder_id != DEMO_ID:
            yield VisitorWrite(folder_id=folder_id)
            return
        with self._write() as db:
            row = _require_folder(db, folder_id)
            target = new_folder_id()
            stamp = now()
            db.execute(
                "INSERT INTO folders (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (target, row["name"], stamp, stamp),
            )
            cards: dict[int, int] = {}
            notes: dict[int, int] = {}
            for card in db.execute(LIVE_CARDS, (folder_id,)).fetchall():
                saved = db.execute(
                    "INSERT INTO cards (folder_id, card_key, chamber, district, priority, reason,"
                    " status, created_at, updated_at) SELECT ?, card_key, chamber, district,"
                    " priority, reason, status, created_at, updated_at FROM cards WHERE id = ?"
                    " RETURNING id",
                    (target, card["id"]),
                ).fetchone()
                cards[card["id"]] = saved[0]
            for note in db.execute(LIVE_NOTES, (folder_id,)).fetchall():
                saved = db.execute(
                    "INSERT INTO notes (card_id, dated, body, confirmed, created_at, updated_at)"
                    " VALUES (?, ?, ?, 1, ?, ?) RETURNING id",
                    (cards[note["card_id"]], note["dated"], note["body"], stamp, stamp),
                ).fetchone()
                notes[note["id"]] = saved[0]
            self._transaction = db
            try:
                yield VisitorWrite(folder_id=target, cards=cards, notes=notes)
            finally:
                self._transaction = None

    @checked
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

    @checked
    def save_case(
        self, folder_id: FolderId, case_id: CaseId, chamber: Chamber, district: District
    ) -> None:
        """Add a case by its id and district; saving it again keeps the card as it is."""
        with self._write() as db:
            _require_mutable(db, folder_id)
            _insert_card(db, folder_id, case_id, chamber, district)
            _touch(db, folder_id)

    @checked
    def set_priority(
        self, folder_id: FolderId, card_id: CardId, priority: Priority, reason: Reason | None
    ) -> None:
        """None stores no reason; an empty or blank string is still refused."""
        with self._write() as db:
            _update_card(db, folder_id, card_id, "priority = ?, reason = ?", priority, reason)

    @checked
    def set_status(self, folder_id: FolderId, card_id: CardId, status: Status) -> None:
        with self._write() as db:
            _update_card(db, folder_id, card_id, "status = ?", status)

    @checked
    def get_folder(self, folder_id: FolderId) -> Folder:
        with closing(self._connect()) as db:
            row = _require_folder(db, folder_id)
            cards = db.execute(LIVE_CARDS, (folder_id,)).fetchall()
        return Folder(id=row["id"], name=row["name"], cards=tuple(Card(**dict(c)) for c in cards))

    @checked
    def rotate_link(self, folder_id: FolderId) -> str:
        """Move everything to a new id in one transaction; the old link is then simply unknown."""
        new_id = new_folder_id()
        with self._write() as db:
            _require_mutable(db, folder_id)
            db.execute(
                "INSERT INTO folders (id, name, created_at, updated_at)"
                " SELECT ?, name, created_at, ? FROM folders WHERE id = ?",
                (new_id, now(), folder_id),
            )
            db.execute("UPDATE cards SET folder_id = ? WHERE folder_id = ?", (new_id, folder_id))
            db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        return new_id

    @checked
    def add_note(
        self, folder_id: FolderId, card_id: CardId, body: NoteBody, confirmed: Literal[True]
    ) -> int:
        """A note on a live card of this folder; `confirmed` is the office's word, always true."""
        with self._write() as db:
            _require_mutable(db, folder_id)
            stamp = now()
            added = db.execute(
                "INSERT INTO notes (card_id, dated, body, confirmed, created_at, updated_at)"
                " SELECT id, ?, ?, ?, ?, ? FROM cards"
                " WHERE id = ? AND folder_id = ? AND deleted_at IS NULL RETURNING id",
                (stamp[:10], body, confirmed, stamp, stamp, card_id, folder_id),
            ).fetchall()
            if not added:
                raise FolderNotFoundError
            _touch(db, folder_id)
        return int(added[0]["id"])

    @checked
    def edit_note(
        self, folder_id: FolderId, note_id: NoteId, body: NoteBody, confirmed: Literal[True]
    ) -> None:
        with self._write() as db:
            _require_mutable(db, folder_id)
            changed = db.execute(
                "UPDATE notes SET body = ?, confirmed = ?, updated_at = ?"
                " WHERE id = ? AND deleted_at IS NULL AND card_id IN"
                " (SELECT id FROM cards WHERE folder_id = ? AND deleted_at IS NULL)",
                (body, confirmed, now(), note_id, folder_id),
            )
            if changed.rowcount != 1:
                raise FolderNotFoundError
            _touch(db, folder_id)

    @checked
    def delete_note(self, folder_id: FolderId, note_id: NoteId) -> None:
        """Move a live note of this folder to the trash (`deleted_at`); a purge removes it."""
        with self._write() as db:
            _require_mutable(db, folder_id)
            stamp = now()
            changed = db.execute(
                "UPDATE notes SET deleted_at = ?, updated_at = ?"
                " WHERE id = ? AND deleted_at IS NULL AND card_id IN"
                " (SELECT id FROM cards WHERE folder_id = ? AND deleted_at IS NULL)",
                (stamp, stamp, note_id, folder_id),
            )
            if changed.rowcount != 1:
                raise FolderNotFoundError
            _touch(db, folder_id)

    @checked
    def list_notes(self, folder_id: FolderId) -> tuple[Note, ...]:
        with closing(self._connect()) as db:
            _require_folder(db, folder_id)
            notes = db.execute(LIVE_NOTES, (folder_id,)).fetchall()
        return tuple(Note(**dict(note)) for note in notes)

    @checked
    def spend_rate(self, rules: tuple[RateRule, ...]) -> None:
        """Count one hit on every rule, or on none: one refusal leaves all counters as they were."""
        with self._write() as db:
            moment = int(datetime.fromisoformat(now()).timestamp())
            for rule in rules:
                row = db.execute(
                    "SELECT window_start, hits FROM rate_buckets WHERE scope = ?", (rule.scope,)
                ).fetchone()
                if row is None or moment - row["window_start"] >= rule.window_seconds:
                    start, hits = moment, 0
                else:
                    start, hits = row["window_start"], row["hits"]
                if hits >= rule.limit:
                    raise RateLimitedError(start + rule.window_seconds - moment)
                db.execute(
                    "INSERT INTO rate_buckets (scope, window_start, hits) VALUES (?, ?, ?)"
                    " ON CONFLICT (scope) DO UPDATE SET"
                    " window_start = excluded.window_start, hits = excluded.hits",
                    (rule.scope, start, hits + 1),
                )

    def purge_expired(self, *, dry_run: bool = False) -> Purged:
        """Hard-delete what has expired. Deleting only frees space, so no size ceiling applies."""
        with self._capacity(), closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            stamp = now()
            cutoff = expiry_cutoff(stamp)
            stale = int(datetime.fromisoformat(stamp).timestamp()) - RATE_BUCKET_TTL_SECONDS
            purged = Purged(
                folders=db.execute(
                    "DELETE FROM folders WHERE updated_at <= ? OR deleted_at <= ?", (cutoff, cutoff)
                ).rowcount,
                cards=db.execute("DELETE FROM cards WHERE deleted_at <= ?", (cutoff,)).rowcount,
                notes=db.execute("DELETE FROM notes WHERE deleted_at <= ?", (cutoff,)).rowcount,
                rate_buckets=db.execute(
                    "DELETE FROM rate_buckets WHERE window_start <= ?", (stale,)
                ).rowcount,
            )
            db.execute("ROLLBACK" if dry_run else "COMMIT")
            if not dry_run:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()  # the WAL held copies
        return purged
