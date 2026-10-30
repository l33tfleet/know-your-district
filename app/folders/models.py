"""Validated shapes for the folder store: keys and office state, never figures.

Text is staff writing about programs and populations, so it is checked at this edge. Contact
details are refused because the store holds no data about individuals (AGENTS.md rule 4).
"""

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from etl.boundaries import DistrictId

MAX_NAME_CHARS = 120
MAX_REASON_CHARS = 200
MAX_NOTE_CHARS = 2000

_CONTACT = re.compile(
    r"\S+@\S+\.\S+"  # email
    r"|\b\d{3}-\d{2}-\d{4}\b"  # Social Security number
    r"|(?:\(\d{3}\)\s*|\b\d{3}[-. ])?\b\d{3}[-. ]\d{4}\b"  # phone, with or without area code
)


def _body(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").strip()
    if any((ord(char) < 32 and char != "\n") or ord(char) == 127 for char in text):
        raise ValueError("control characters are unsupported")
    if _CONTACT.search(text):
        raise ValueError("contact details are refused: folders hold no data about individuals")
    return text


def _line(value: object) -> object:
    if isinstance(value, str) and "\n" in value.strip():
        raise ValueError("must be one line")
    return _body(value)


FolderName = Annotated[
    str,
    BeforeValidator(_line),
    StringConstraints(strict=True, min_length=1, max_length=MAX_NAME_CHARS),
]
Reason = Annotated[
    str,
    BeforeValidator(_line),
    StringConstraints(strict=True, min_length=1, max_length=MAX_REASON_CHARS),
]
NoteBody = Annotated[
    str,
    BeforeValidator(_body),
    StringConstraints(strict=True, min_length=1, max_length=MAX_NOTE_CHARS),
]
# Hyphenated, so `snap-b22003` fits; no room for `?`, `#`, `%`, `/` or `..`.
CardKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]
# Names an action or folder. No dots or colons, so it cannot hold an IP address.
RateScope = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,64}$")]


class CardStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SET_ASIDE = "set_aside"


class Priority(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class NewFolder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: FolderName


class CardState(BaseModel):
    """The office's own state for a card."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: CardStatus = CardStatus.NEW
    priority: Priority = Priority.NORMAL
    reason: Reason | None = None


class NewCard(BaseModel):
    """A card names what it is about; pages re-read its numbers from the fact table."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    card_key: CardKey
    district: DistrictId
    state: CardState = CardState()


class NewNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dated: date
    body: NoteBody
    confirmed: bool = False


class RateHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: RateScope
    limit: Annotated[int, Field(gt=0)]
    window_seconds: Annotated[int, Field(gt=0)]


class Folder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    folder_id: str
    card_key: str
    district: DistrictId
    state: CardState
    created_at: datetime
    updated_at: datetime


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    card_id: int
    dated: date
    body: str
    confirmed: bool
    created_at: datetime
    updated_at: datetime
