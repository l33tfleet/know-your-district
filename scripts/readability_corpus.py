"""Offline readability inputs, kept as separate leaves/blocks rather than page averages."""

import argparse
import json
import re
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, StrictInt

from scripts.readability import HAWAIIAN_NAMES, score, syllables


@dataclass(frozen=True)
class Block:
    id: str
    source: str
    text: str
    citation_spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Corpus:
    blocks: tuple[Block, ...]
    absent: tuple[str, ...]


def yaml_blocks(path: Path) -> list[Block]:
    """Keep every scalar, including non-prose values, with its YAML key/index path."""
    result: list[Block] = []

    def walk(value: object, keys: list[str | int]) -> None:
        if isinstance(value, dict):
            for key, child in cast(dict[str, object], value).items():
                walk(child, [*keys, key])
        elif isinstance(value, list):
            for index, child in enumerate(cast(list[object], value)):
                walk(child, [*keys, index])
        else:
            result.append(
                Block(f"{path}:{json.dumps(keys)}", str(path), "" if value is None else str(value))
            )

    walk(yaml.safe_load(path.read_text(encoding="utf-8")), [])
    return result


# Only individual metadata values are exempt. In particular, method, uncertainty,
# labels, summaries and caveats inside a citation/details container still score.
_CITATION_FIELDS = {"source", "table_id", "vintage", "geography", "endpoint"}
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "button",
    "caption",
    "dd",
    "details",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "label",
    "legend",
    "li",
    "main",
    "nav",
    "ol",
    "option",
    "p",
    "pre",
    "section",
    "select",
    "summary",
    "table",
    "td",
    "text",
    "th",
    "title",
    "ul",
}
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _Blocks(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.blocks: list[Block] = []
        self.stack: list[tuple[str, bool, bool]] = []
        self.parts: list[tuple[str, bool]] = []

    def emit(self, text: str, spans: tuple[tuple[int, int], ...] = ()) -> None:
        if text.strip():
            self.blocks.append(Block(f"{self.source}#{len(self.blocks)}", "rendered", text, spans))

    def flush(self) -> None:
        text = "".join(part for part, _ in self.parts)
        spans: list[tuple[int, int]] = []
        offset = 0
        for part, cited in self.parts:
            if cited and part:
                spans.append((offset, offset + len(part)))
            offset += len(part)
        self.emit(text, tuple(spans))
        self.parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        ignored = tag in {"script", "style", "template"} or any(s[2] for s in self.stack)
        if ignored:
            if tag not in _VOID:
                self.stack.append((tag, False, True))
            return
        if tag in _BLOCK_TAGS:
            self.flush()
        for name in ("aria-label", "alt", "placeholder", "title"):
            value = attributes.get(name)
            if value:
                self.emit(value)
        if tag == "input" and attributes.get("type") in {"submit", "button", "reset"}:
            self.emit(attributes.get("value") or "")
        cited = (tag in {"dd", "code"} and attributes.get("data-field") in _CITATION_FIELDS) or any(
            s[1] for s in self.stack
        )
        if tag not in _VOID:
            self.stack.append((tag, cited, False))
        if tag == "br":
            self.parts.append(("\n", False))

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not any(s[2] for s in self.stack):
            if not any(s[0] == "pre" for s in self.stack):
                data = re.sub(r"[ \t\r\n\f]+", " ", data)
            self.parts.append((data, any(s[1] for s in self.stack)))


def rendered_blocks(html: str, source: str) -> list[Block]:
    parser = _Blocks(source)
    parser.feed(html)
    parser.close()
    parser.flush()
    return parser.blocks


class _Recording(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    kind: Literal["answer", "refusal"]
    text: str
    citation_spans: list[tuple[StrictInt, StrictInt]]


def recorded_blocks(path: Path) -> list[Block]:
    """Replay original JSONL text/character offsets; never call a model."""
    result: list[Block] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        record = _Recording.model_validate_json(line)
        if not record.id.strip():
            raise ValueError("recording id must be nonempty")
        if record.id in seen:
            raise ValueError(f"duplicate recording id: {record.id}")
        seen.add(record.id)
        score(record.text, record.citation_spans)  # validate original offsets
        result.append(
            Block(f"{path}:{record.id}", record.kind, record.text, tuple(record.citation_spans))
        )
    return result


GRADE_LIMIT = 8.0
LABEL_MAX_WORDS = 3
LABEL_MAX_SYLLABLES = 3
PLACEHOLDER = "Name"
# The one fixed statement scored as a placeholder (docs/plain-language.md).
AGENCY_STATEMENT = "The agency decides eligibility."
REFERRAL_NAME = "Aloha United Way"
_ROOT = Path(__file__).resolve().parents[1]
_BRACES = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z_0-9]*\s*\}\}|\{[A-Za-z_][A-Za-z_0-9]*\}")
_WORD = re.compile(r"[A-Za-zĀĒĪŌŪāēīōū]+(?:[ʻ'\u2019][A-Za-zĀĒĪŌŪāēīōū]+)*|\d+(?:[.,]\d+)*")


@cache
def placeholder_names(root: Path = _ROOT) -> tuple[str, ...]:
    """Fixed names read from the repo's own data, plus the agency statement.

    Catalog program names and agencies (data/programs.yaml), county names
    (app/copy.yaml `counties`), island names (data/geo/islands/islands.json),
    Aloha United Way and the sentence "The agency decides eligibility." Longest
    first, so a longer name is replaced before a name it contains.
    """
    names: set[str] = {REFERRAL_NAME, AGENCY_STATEMENT}
    for record in cast(
        list[dict[str, object]],
        yaml.safe_load((root / "data/programs.yaml").read_text(encoding="utf-8")),
    ):
        names.update(str(record[key]) for key in ("name", "agency"))
    copy = cast(dict[str, object], yaml.safe_load((root / "app/copy.yaml").read_text("utf-8")))
    names.update(str(name) for name in cast(dict[str, object], copy["counties"]).values())
    islands = cast(
        dict[str, list[dict[str, object]]],
        json.loads((root / "data/geo/islands/islands.json").read_text(encoding="utf-8")),
    )
    names.update(str(island["name"]) for island in islands["islands"])
    return tuple(sorted(names, key=lambda name: (-len(name), name)))


@dataclass(frozen=True)
class Reading:
    """How one page string reads after citation removal and name placeholders."""

    text: str
    label: bool
    grade: float | None
    long_words: tuple[str, ...]

    @property
    def ok(self) -> bool:
        if self.label:
            return not self.long_words
        return self.grade is None or self.grade <= GRADE_LIMIT


def check_reading(
    text: str,
    citation_spans: tuple[tuple[int, int], ...] = (),
    names: tuple[str, ...] | None = None,
) -> Reading:
    """Score one string under the page rule in docs/plain-language.md.

    Citation spans become a space; each exact fixed name becomes "Name". A string
    of 1–3 words with no sentence-ending punctuation is a label: every word other
    than a placeholder or an exempt Hawaiian name must have at most three
    syllables. Every other string must score Flesch–Kincaid grade 8 or lower.
    """
    score(text, citation_spans)  # validate the spans
    parts: list[str] = []
    previous = 0
    for start, end in citation_spans:
        parts.extend((text[previous:start], " "))
        previous = end
    parts.append(text[previous:])
    plain = unicodedata.normalize("NFC", "".join(parts))
    plain = _BRACES.sub("one", plain)  # a copy placeholder is one short word, as in score()
    for name in placeholder_names() if names is None else names:
        plain = plain.replace(unicodedata.normalize("NFC", name), PLACEHOLDER)
    # Exempt Hawaiian names count as no word, as in score().
    words = [word for word in _WORD.findall(plain) if word not in HAWAIIAN_NAMES]
    label = 1 <= len(words) <= LABEL_MAX_WORDS and not re.search(r"[.!?]", plain)
    long_words = tuple(
        word for word in words if word != PLACEHOLDER and syllables(word) > LABEL_MAX_SYLLABLES
    )
    return Reading(plain, label, score(plain).grade, long_words if label else ())


_URL = re.compile(r"https?://\S+")


def page_blocks(pages: Mapping[str, str], root: Path = _ROOT) -> list[Block]:
    """The page strings the rule covers: every rendered block, and every app/copy.yaml
    leaf except a bare URL (a link target, not text a reader reads)."""
    blocks = [b for source, html in pages.items() for b in rendered_blocks(html, source)]
    blocks.extend(b for b in yaml_blocks(root / "app/copy.yaml") if not _URL.fullmatch(b.text))
    return blocks


def hard_blocks(blocks: list[Block]) -> list[tuple[Block, Reading]]:
    """Each block that breaks the page rule, with how it read."""
    failed: list[tuple[Block, Reading]] = []
    for block in blocks:
        reading = check_reading(block.text, block.citation_spans)
        if not reading.ok:
            failed.append((block, reading))
    return failed


def rendered_pages() -> dict[str, str]:
    """Render the real app offline, plus labelled missing-row and county fixtures."""
    from fastapi.testclient import TestClient

    from app.brief import discover, render_context
    from app.brief_facts import FORMATS
    from app.brief_facts import reading as figure_reading
    from app.copy import section_copy
    from app.main import app, templates
    from app.page_state import PageState
    from etl.boundaries import DISTRICT_COUNTS, DistrictId

    paths = ["/", "/not-found", *[f"/picker/numbers?chamber={c}" for c in DISTRICT_COUNTS]]
    paths.extend(
        f"/brief/{c}/{n}" for c, count in DISTRICT_COUNTS.items() for n in range(1, count + 1)
    )
    with TestClient(app) as client:
        pages = {path: client.get(path).text for path in paths}
    section = next(s for s in discover() if s.name == "figures")
    context = render_context(section, PageState(district=DistrictId(chamber="house", district=1)))
    content = cast(dict[str, object], context["section"])
    # The committed overlay currently has only single-county districts. Exercise
    # the multi-county template branch explicitly, without claiming a real split.
    multi = deepcopy(context)
    multi_content = cast(dict[str, object], multi["section"])
    multi_content.update(
        multi_county=True,
        county_shares=[
            {"name": "Hawaiʻi County", "share_text": "synthetic fixture"},
            {"name": "Maui County", "share_text": "synthetic fixture"},
        ],
    )
    pages["fixture:multi-county"] = templates.get_template(section.template).render(multi)
    # Every reading missing, worded by the app's own reading() (app/copy.yaml), and laid
    # out as the app lays out a figure with no row at all: no sentence, no citation.
    figures_copy = section_copy("figures")
    for figure in cast(list[dict[str, object]], content["figures"]):
        readings = [cast(dict[str, object], figure[k]) for k in ("district", "state")]
        readings.extend(cast(list[dict[str, object]], figure["counties"]))
        for reading in readings:
            kept = {k: reading[k] for k in ("geography", "label") if k in reading}
            reading.clear()
            fmt = FORMATS[str(figure["key"])]
            reading.update(figure_reading(str(kept["geography"]), None, fmt, figures_copy))
            reading.update(kept)
        figure.update(citations=[], intervals=[], sentence=[], count_sentence=[])
    pages["fixture:missing-figures"] = templates.get_template(section.template).render(context)
    return pages


def collect(root: Path, *, pages: Mapping[str, str], recordings: Path | None = None) -> Corpus:
    blocks: list[Block] = []
    absent: list[str] = []
    paths = {root / "app/copy.yaml", root / "data/programs.yaml"}
    for directory in ("app", "data"):
        paths.update((root / directory).rglob("*.yaml"))
        paths.update((root / directory).rglob("*.yml"))
    for path in sorted(paths):
        leaves = yaml_blocks(path) if path.exists() else []
        blocks.extend(leaves)
        if not any(score(b.text).grade is not None for b in leaves):
            absent.append(str(path.relative_to(root)))
    if not pages:
        absent.append("rendered")
    for source, html in pages.items():
        rendered = rendered_blocks(html, source)
        blocks.extend(rendered)
        if not any(score(b.text, b.citation_spans).grade is not None for b in rendered):
            absent.append(f"rendered:{source}")
    recorded = recorded_blocks(recordings) if recordings is not None else []
    blocks.extend(recorded)
    for kind in ("answer", "refusal"):
        if not any(
            b.source == kind and score(b.text, b.citation_spans).grade is not None for b in recorded
        ):
            absent.append(kind)
    return Corpus(tuple(blocks), tuple(absent))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings", type=Path, help="Offline answer/refusal JSONL")
    args = parser.parse_args()
    corpus = collect(
        Path(__file__).resolve().parents[1], pages=rendered_pages(), recordings=args.recordings
    )
    print(
        json.dumps(
            {
                "absent": corpus.absent,
                "blocks": [
                    asdict(b) | {"score": asdict(score(b.text, b.citation_spans))}
                    for b in corpus.blocks
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
