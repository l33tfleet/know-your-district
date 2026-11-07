"""Office notes on a saved case: the check before a save, and how a refusal reads.

Nothing here writes. `FolderService` screens the words, binds a confirmation to them and counts
the write; `app/folders/store.py` stores them. A phone number, email address or street address is
always refused and must be removed: no confirmation lifts that. Clean words get a confirmation
token, which the save step must send back with exactly those words.
"""

from collections.abc import Mapping
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.copy import Copy
from app.folders.service import (
    ConfirmationRequiredError,
    FolderService,
    NoteRefusedError,
    PiiBlockedError,
)

MAX_CHARACTERS = 1000
# The characters `NoteText` refuses: tabs and line breaks are kept.
CONTROL = set(range(0x00, 0x20)) - {0x09, 0x0A, 0x0D} | set(range(0x7F, 0xA0)) | {0x2028, 0x2029}
# What a save step can raise for the words themselves; each becomes a plain message.
REFUSALS = (NoteRefusedError, PiiBlockedError, ConfirmationRequiredError)


class Draft(BaseModel):
    """Words that are not saved yet: refused with a message, or waiting for the confirm step."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    card_id: int
    note_id: int | None  # None for a new note
    body: str = Field(repr=False)
    token: str | None = Field(default=None, repr=False)
    refusal: str | None = None


def read_body(form: Mapping[str, str]) -> str:
    """The note as typed. Forms send line breaks as CRLF; the check and the save read LF."""
    return form.get("body", "").replace("\r\n", "\n").replace("\r", "\n")


def refusal(body: str, error: Exception, words: Copy) -> str:
    """The plain message for words that cannot be saved as they are."""
    if isinstance(error, PiiBlockedError):
        return str(words["note_personal"])
    if isinstance(error, ConfirmationRequiredError):
        return str(words["note_unconfirmed"])
    if len(body) > MAX_CHARACTERS:
        return str(words["note_too_long"]).format(limit=MAX_CHARACTERS, count=len(body))
    if any(ord(char) in CONTROL for char in body):
        return str(words["note_control"])
    return str(words["note_blank"])


def check(
    folders: FolderService,
    folder_id: str,
    card_id: int,
    note_id: int | None,
    body: str,
    words: Copy,
) -> Draft:
    """The confirm step's token for clean words, or the refusal; never a write."""
    try:
        token = folders.confirmation(folder_id, body)
    except (NoteRefusedError, PiiBlockedError) as exc:
        return Draft(card_id=card_id, note_id=note_id, body=body, refusal=refusal(body, exc, words))
    return Draft(card_id=card_id, note_id=note_id, body=body, token=token)


def date_label(dated: str) -> str:
    """`2026-10-20` as `20 October 2026`, the way the brief writes dates."""
    day = date.fromisoformat(dated)
    return f"{day.day} {day:%B %Y}"
