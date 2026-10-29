"""Small, deterministic Flesch–Kincaid scorer; contract in docs/plain-language.md."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

HAWAIIAN_NAMES = frozenset(
    {"Hawaiʻi", "Kauaʻi", "Lānaʻi", "Molokaʻi", "Oʻahu", "Kahoʻolawe", "Niʻihau"}
)
_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z_0-9]*\s*\}\}|\{[A-Za-z_][A-Za-z_0-9]*\}")
_LETTERS = "A-Za-zĀĒĪŌŪāēīōū"
_TOKEN = re.compile(rf"[{_LETTERS}]+(?:[ʻ'\u2019][{_LETTERS}]+)*|\d+(?:[.,]\d+)*|[.!?\n]+")


@dataclass(frozen=True)
class Score:
    words: int
    sentences: int
    syllables: int
    grade: float | None


def syllables(word: str) -> int:
    """Estimate one token's syllables, with at least one per token."""
    word = unicodedata.normalize("NFC", word).lower().translate(str.maketrans("āēīōū", "aeiou"))
    word = re.sub(r"[^a-z0-9]", "", word)
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not re.search(r"[^aeiouy]le$", word):
        count -= 1
    if word.endswith("ed") and not word.endswith(("ted", "ded")):
        count -= 1
    if word.endswith("es") and not re.search(r"(?:[sxz]|ch|sh|[^aeiouy]l)es$", word):
        count -= 1
    return max(1, count)


def score(text: str, citation_spans: Sequence[tuple[int, int]] = ()) -> Score:
    """Score plain text; citation spans are sorted, half-open character offsets."""
    parts: list[str] = []
    previous = 0
    for start, end in citation_spans:
        if not 0 <= start < end <= len(text):
            raise ValueError("citation span must satisfy 0 <= start < end <= len(text)")
        if start < previous:
            raise ValueError("citation spans must be sorted and disjoint")
        parts.extend((text[previous:start], " "))
        previous = end
    parts.append(text[previous:])
    cleaned = unicodedata.normalize("NFC", "".join(parts))
    cleaned = _PLACEHOLDER.sub("one", cleaned)
    words = sentences = total_syllables = pending = 0
    for match in _TOKEN.finditer(cleaned):
        token = match.group()
        if token[0] in ".!?\n":
            if pending:
                sentences += 1
                pending = 0
        elif token not in HAWAIIAN_NAMES:
            words += 1
            pending += 1
            total_syllables += syllables(token)
    sentences += bool(pending)
    grade = 0.39 * words / sentences + 11.8 * total_syllables / words - 15.59 if words else None
    return Score(words, sentences, total_syllables, grade)
