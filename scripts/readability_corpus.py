"""Offline readability inputs, kept as separate leaves/blocks rather than page averages."""

import argparse
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, StrictInt

from scripts.readability import score


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


def rendered_pages() -> dict[str, str]:
    """Render the real app offline, plus labelled missing-row and county fixtures."""
    from fastapi.testclient import TestClient

    from app.brief import discover, render_context
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
    for figure in cast(list[dict[str, object]], content["figures"]):
        readings = [cast(dict[str, object], figure[k]) for k in ("district", "state")]
        readings.extend(cast(list[dict[str, object]], figure["counties"]))
        for reading in readings:
            reading.update(
                found=False,
                value_text="not available",
                word="not available",
                reliability="unavailable",
            )
        figure.update(citations=[], intervals=[])
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
