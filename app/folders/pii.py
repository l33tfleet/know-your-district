"""Finds personal contact details in office text, and binds a confirmation to exact words.

`find` is a hard block: nothing overrides it. It reads a canonical copy of the text, so fullwidth
forms and invisible characters cannot hide a detail. A confirmation is the office's statement
about one exact text, so it hashes the words as submitted, uncanonicalized.
"""

import hashlib
import hmac
import re
import unicodedata
from typing import Literal

Kind = Literal["phone", "email", "address"]

_STREET = r"(?<![\w-])\d{1,6}(?:-\d{1,4})?[A-Za-z]?\s+(?:[^\W\d][\w'.-]*\s+){1,4}?"  # number, name
_PATTERNS: tuple[tuple[Kind, re.Pattern[str]], ...] = (
    (
        "phone",
        re.compile(
            r"(?<![\w.])(?:\+?1[\s.-]*)?(?:\(\d{3}\)|\d{3})[\s.-]*\d{3}[\s.-]*\d{4}(?!\d)"  # US
            r"|(?<![\w.-])\d{3}[.-]\d{4}(?![\d-])"  # local, as Hawaiʻi offices write it
            r"|(?<![\w.])\+\d[\d\s().-]{6,}\d"  # international
        ),
    ),
    (
        "email",
        re.compile(
            r"[\w.+-]+\s*(?:@|\(at\)|\[at\])\s*[\w-]+"
            r"(?:\s*(?:\.|\(dot\)|\[dot\])\s*[\w-]+)+",
            re.IGNORECASE,
        ),
    ),
    # Suffixes that are rarely ordinary words, in any case.
    (
        "address",
        re.compile(
            _STREET + r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|highway|hwy|parkway|pkwy)\b",
            re.IGNORECASE,
        ),
    ),
    # Suffixes that are also ordinary words: only a capitalized street name counts.
    (
        "address",
        re.compile(
            r"(?<![\w-])\d{1,6}(?:-\d{1,4})?[A-Za-z]?\s+(?:[A-Z][\w'.-]*\s+){1,4}?"
            r"(?:Way|Place|Pl|Court|Ct|Drive|Dr|Lane|Ln|Loop|Circle|Cir|Terrace|Ter)\b"
        ),
    ),
    (
        "address",
        re.compile(
            r"\bp\.?\s*o\.?\s*box\s*\d|\b(?:apt|apartment)\.?\s*#?\s*\d|\bunit\s*#\s*\d",
            re.IGNORECASE,
        ),
    ),
)


def _canonical(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(char for char in folded if unicodedata.category(char) != "Cf")


def find(text: str) -> tuple[Kind, ...]:
    """The kinds of personal detail in `text`, phone first; empty when there are none."""
    canonical = _canonical(text)
    found: list[Kind] = [kind for kind, pattern in _PATTERNS if pattern.search(canonical)]
    return tuple(dict.fromkeys(found))


def confirmation_token(secret: bytes, folder_id: str, text: str) -> str:
    message = f"{folder_id}\0{text}".encode()
    return hmac.new(secret, b"note-confirmation\0" + message, hashlib.sha256).hexdigest()


def confirmation_matches(secret: bytes, folder_id: str, text: str, given: str) -> bool:
    expected = confirmation_token(secret, folder_id, text).encode()
    return hmac.compare_digest(expected, given.encode("utf-8", "replace"))
