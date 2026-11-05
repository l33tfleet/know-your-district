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

# Candidate detection must include every street word: even "A" and "Kupuna" can name
# a street. Only a complete candidate in a narrow office-prose context is exempt.
_STREET_WORD = r"(?:\d+(?:st|nd|rd|th)|'?[^\W\d][\w'.-]*)"
_STREET = r"(?<![\w-])\d{1,6}(?:-\d{1,4})?(?:-?[A-Za-z])?\s+" + rf"(?:{_STREET_WORD}\s+){{1,4}}?"
# Year-shaped house numbers are still addresses: exempt only the established lowercase
# event prose. Kūpuna can name a street, so it is never exempt before a bare "Drive".
_OFFICE_PROSE = re.compile(
    r"(?:(?:19|20)\d{2}\s+(?-i:food\s+drive|district\s+court)"
    r"|\d+\s+(?:people|families|parents|staff|programs)\s+drive"
    r"|\d+\s+(?:people|families|parents|staff|programs|kupuna|kūpuna)\s+"
    r"(?:in\s+place|are\s+(?:at\s+a\s+place|on\s+the\s+way)"
    r"|asked\s+about\s+the\s+court|came\s+and\s+the\s+place))",
    re.IGNORECASE,
)
# A local-number-shaped bill/year pair is safe only within an explicit reference.
# Compare exact spans below, so neither a longer phone nor a second contact is hidden.
_LEGISLATIVE_REFERENCE = re.compile(
    r"(?<!\w)(?:HB|SB|Act)\s+(?P<pair>\d{3}[\s./-](?:19|20)\d{2})(?!\w)",
    re.IGNORECASE,
)
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
    references = {match.span("pair") for match in _LEGISLATIVE_REFERENCE.finditer(canonical)}
    found: list[Kind] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(canonical):
            if kind == "phone" and match.span() in references:
                continue
            if kind == "address" and _OFFICE_PROSE.fullmatch(match.group()):
                continue
            found.append(kind)
            break
    return tuple(dict.fromkeys(found))


def confirmation_token(secret: bytes, folder_id: str, text: str) -> str:
    message = f"{folder_id}\0{text}".encode()
    return hmac.new(secret, b"note-confirmation\0" + message, hashlib.sha256).hexdigest()


def confirmation_matches(secret: bytes, folder_id: str, text: str, given: str) -> bool:
    expected = confirmation_token(secret, folder_id, text).encode()
    return hmac.compare_digest(expected, given.encode("utf-8", "replace"))
