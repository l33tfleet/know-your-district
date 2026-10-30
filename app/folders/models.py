"""Validated shapes for the folder store: keys and office state, never figures.

Rule 4 is held by a closed vocabulary, not by spotting bad text. Office text uses letters, basic
punctuation and `OFFICE_WORDS` only, so a name, an address, a contact detail or a figure has no
way in. The list has programs, places, office actions and plural populations; it leaves out
pronouns, singular words for a person, and words that double as given names (may, will, mark).
Widen it by review, one word at a time, with the same test in mind.
"""

import re
import unicodedata
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from etl.boundaries import DistrictId

MAX_NAME_CHARS = 120
MAX_REASON_CHARS = 200
MAX_NOTE_CHARS = 2000

_WORD_LIST = """
    a about after all an and any are as at before by each few for from in into is it its more
    most next no not of on or our than that the then there these this those to up was we were
    what when where which why with without yes

    add added ask asked attend attended book booked brief briefed call called check checked
    confirm confirmed contact contacted create created discuss discussed draft drafted email
    emailed follow invite invited mail mailed meet met plan planned post posted print printed
    refer referred reply replied request requested review reviewed schedule scheduled send sent
    share shared update updated visit visited wait waiting

    action actions agencies agency answer answers application applications briefing card cards
    case cases center centers clinics communities community council deadline deadlines district
    districts event events fair fairs flyer flyers folder folders form forms gap gaps hearing
    hearings hours languages letter letters list lists meeting meetings navigator navigators
    need needs note notes notice notices office offices outreach partners population populations
    priority program programs question questions referral referrals report reports rule rules
    schools session sessions sites staff step steps summary teams time today tomorrow topic
    topics week weeks month months year years workshop workshops

    adults children elders families farmers households immigrants keiki kūpuna parents renters
    residents seniors students tenants veterans workers youth

    benefit benefits care childcare disabilities disability energy food health healthcare
    housing income insurance medical nutrition poverty rent rental unemployment utilities

    aloha county department dhs federal human liheap med medicaid medicare public quest services
    snap ssi state tanf united way wic

    hawaiʻi oʻahu kauaʻi maui molokaʻi lānaʻi niʻihau kahoʻolawe hilo honolulu kailua kalihi
    kapolei kona waipahu waiʻanae

    closed done first high last local low new open pending urgent
"""
OFFICE_WORDS = frozenset(_WORD_LIST.split())

_OFFICE_TEXT = re.compile(r"(?:[^\W\d_]|[ \n,.;:?()/-])*")
_WORD = re.compile(r"[^\W\d_]+")
_TABLE_ID = re.compile(r"[a-z]\d{5}[a-z]?")
_REFUSED = "folders hold no data about individuals"


def _text(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").strip()
    if not _OFFICE_TEXT.fullmatch(text):
        raise ValueError(f"only letters and basic punctuation are accepted: {_REFUSED}")
    for word in _WORD.findall(text.casefold()):
        if word not in OFFICE_WORDS:
            raise ValueError(f"'{word}' is not an office word: {_REFUSED}")
    return text


def _line(value: object) -> object:
    if isinstance(value, str) and "\n" in value.strip():
        raise ValueError("must be one line")
    return _text(value)


def _key(value: str) -> str:
    for part in value.split("-"):
        if part not in OFFICE_WORDS and not _TABLE_ID.fullmatch(part):
            raise ValueError(f"'{part}' is not an office word or table ID: {_REFUSED}")
    return value


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
    BeforeValidator(_text),
    StringConstraints(strict=True, min_length=1, max_length=MAX_NOTE_CHARS),
]
# Words and table IDs joined by hyphens, like `snap-b22003`; no `?`, `#`, `%`, `/` or `..`.
Key = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64),
    AfterValidator(_key),
]


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
    card_key: Key
    district: DistrictId
    state: CardState = CardState()


class NewNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dated: date
    body: NoteBody
    confirmed: bool = False


class RateHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: Key
    limit: Annotated[int, Field(gt=0)]
    window_seconds: Annotated[int, Field(gt=0)]


class Folder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    folder_id: str
    card_key: str
    district: DistrictId
    state: CardState
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    card_id: int
    dated: date
    body: str
    confirmed: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
