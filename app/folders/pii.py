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

# A street name may be lowercase or ordinal. Ordinary sentence words and counted
# groups are not name evidence (for example, "3 programs in place" or "5 families drive").
_STREET_WORD = (
    r"(?!(?:in|on|the|a|at|are|is|was|were|and|of|to|for|about|asked|have|has|came"
    r"|people|families|staff|programs|kupuna|kūpuna)\b)"
    r"(?:\d+(?:st|nd|rd|th)|[^\W\d][\w'.-]*)"
)
_STREET = r"(?<![\w-])\d{1,6}(?:-\d{1,4})?[A-Za-z]?\s+" + rf"(?:{_STREET_WORD}\s+){{1,4}}?"
_PATTERNS: tuple[tuple[Kind, re.Pattern[str]], ...] = (
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?1[\s./-]*)?(?:\(\d{3}\)|\d{3})[\s./-]*\d{3}[\s./-]*\d{4}(?!\d)"  # US
            r"|(?<![\d.-])\d{3}[\s./-]\d{4}(?![\d-])"  # local, as Hawaiʻi offices write it
            r"|(?<!\d)\+\d[\d\s()./-]{6,}\d"  # international
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
    # Capitalization is not evidence that an address is safe to store.
    (
        "address",
        re.compile(
            _STREET + r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|highway|hwy|parkway|pkwy"
            r"|way|place|pl|court|ct|drive|dr|lane|ln|loop|circle|cir|terrace|ter)\b",
            re.IGNORECASE,
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
    # Word processors substitute curly quotes for apostrophes and the ʻokina.
    # Fold these only in the screening copy; stored and confirmed text stays exact.
    folded = unicodedata.normalize("NFKC", text).translate(
        str.maketrans("\u2018\u2019\u02bc\u02bb", "''''")
    )
    return "".join(
        "-" if unicodedata.category(char) == "Pd" or char == "\u2212" else char
        for char in folded
        if unicodedata.category(char) != "Cf"
    )


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
