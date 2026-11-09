"""WO187: every page string reads at grade 8 or below, and method words stay true.

The rule (docs/plain-language.md, "Page rule"): citation fields stay excluded
exactly as before; fixed names become a placeholder; a 1–3 word label has no word
over three syllables; every other string scores Flesch–Kincaid grade 8 or lower.
"""

from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts.readability_corpus import (
    Block,
    check_reading,
    hard_blocks,
    page_blocks,
    rendered_blocks,
    rendered_pages,
    yaml_blocks,
)

ROOT = Path(__file__).resolve().parents[2]
ZIP_WORDS = "estimated from zip codes"


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return rendered_pages()


def test_every_page_string_reads_at_grade_8_or_below(pages: dict[str, str]) -> None:
    blocks = page_blocks(pages)
    # Coverage: every brief, the home and missing pages, both fixtures and all copy.
    assert len([p for p in pages if p.startswith("/brief/")]) == 51 + 25
    assert {"/", "/not-found", "fixture:multi-county", "fixture:missing-figures"} <= set(pages)
    copy_leaves = [b for b in blocks if b.source.endswith("app/copy.yaml")]
    assert len(copy_leaves) > 300
    failed = [
        f"{block.id}: {reading.grade if not reading.label else reading.long_words} | {block.text}"
        for block, reading in hard_blocks(blocks)
    ]
    assert failed == []


def test_citation_fields_stay_excluded_and_methods_stay_scored(pages: dict[str, str]) -> None:
    html = pages["/brief/house/1"]
    blocks = rendered_blocks(html, "house-1")
    cited = [b for b in blocks if b.citation_spans]
    assert any(b.text == "B01003" and b.citation_spans == ((0, 6),) for b in cited)
    methods = [b for b in blocks if b.text.startswith("published estimate and 90% margin")]
    assert methods and all(not b.citation_spans for b in methods)
    assert any(". MOE controlled. MOE annotation: *****" in b.text for b in methods)


def test_a_hard_string_on_any_page_fails_the_rule(pages: dict[str, str]) -> None:
    hard = "Institutionalization necessitates interdisciplinary administrative operationalization."
    html = pages["/brief/house/1"].replace("</main>", f"<p>{hard}</p></main>", 1)
    failed = hard_blocks(page_blocks({"/brief/house/1": html}))
    assert [b.text for b, _ in failed] == [hard]


@pytest.mark.parametrize(
    "path, old",
    [
        (
            "app/copy.yaml",
            "This figure is not available",
        ),
    ],
)
def test_restoring_an_old_copy_string_fails(tmp_path: Path, path: str, old: str) -> None:
    source = (ROOT / path).read_text(encoding="utf-8")
    assert old in source
    target = tmp_path / "copy.yaml"
    target.write_text(source.replace(old, "not available", 1), encoding="utf-8")
    leaves = [b for b in yaml_blocks(target) if b.text == "not available"]
    assert leaves and not check_reading(leaves[0].text).ok


class _Units(HTMLParser):
    """Group a page's text into figure units: each figure card, case card and table row.

    A unit's methods are its `data-field="method"` values and every `<dd>` that follows
    a "Method" `<dt>`. Text outside every unit is collected separately.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int | None]] = []
        self.units: list[tuple[list[str], list[str]]] = []
        self.loose: list[str] = []
        self.in_method = False
        self.after_method_dt = False
        self.dt_text: list[str] | None = None

    def _unit(self) -> int | None:
        return next((u for _, u in reversed(self.stack) if u is not None), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "wbr", "img", "input", "meta", "link", "hr", "source"}:
            return
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        unit: int | None = None
        if tag == "tr" or {"figure", "case", "match-card"} & classes:
            self.units.append(([], []))
            unit = len(self.units) - 1
        self.stack.append((tag, unit))
        if tag == "dt":
            self.dt_text = []
        if tag == "dd":
            self.in_method = attributes.get("data-field") == "method" or self.after_method_dt
            current = self._unit()
            if self.in_method and current is not None:
                self.units[current][1].append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "dt" and self.dt_text is not None:
            self.after_method_dt = "".join(self.dt_text).strip().lower() == "method"
            self.dt_text = None
        if tag == "dd":
            self.in_method = self.after_method_dt = False
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.dt_text is not None:
            self.dt_text.append(data)
        current = self._unit()
        if current is None:
            self.loose.append(data)
            return
        self.units[current][0].append(data)
        if self.in_method and self.units[current][1]:
            self.units[current][1][-1] += data


def zip_wording_errors(html: str) -> list[str]:
    """Each place "estimated from ZIP codes" appears without a ZIP-based method beside it."""
    parser = _Units()
    parser.feed(html)
    parser.close()
    errors: list[str] = []
    if ZIP_WORDS in " ".join(" ".join(parser.loose).split()).lower():
        errors.append("outside any figure")
    for texts, methods in parser.units:
        text = " ".join(" ".join(texts).split()).lower()
        if ZIP_WORDS in text and not any("zip" in m.lower() for m in methods):
            errors.append(text[:120])
    return errors


def test_zip_wording_appears_only_beside_zip_based_methods(pages: dict[str, str]) -> None:
    for source, html in pages.items():
        assert zip_wording_errors(html) == [], source
    words = [b for b in page_blocks({}) if ZIP_WORDS in b.text.lower()]
    assert words == []  # no copy string claims a ZIP method for every figure


def _figure(label: str, method: str) -> str:
    return (
        '<div class="figure"><p class="reading">1,234 residents, '
        f"{label}.</p><details><dl><dt>Method</dt>"
        f'<dd data-field="method">{method}</dd></dl></details></div>'
    )


@pytest.mark.parametrize(
    "method",
    [
        "published estimate and 90% margin of error",
        "county share of a published county total",
        "summed from published tract estimates",
    ],
)
def test_zip_wording_beside_a_non_zip_method_fails(method: str) -> None:
    assert zip_wording_errors(_figure("estimated from ZIP codes", method))
    # The same words outside any figure are also an error.
    assert zip_wording_errors("<p>Figures are estimated from ZIP codes.</p>")


def test_zip_wording_beside_a_zip_method_passes() -> None:
    zip_method = "ZIP Code Tabulation Area counts allocated to the district by address share"
    assert zip_wording_errors(_figure("estimated from ZIP codes", zip_method)) == []
    # A table row in the SNAP layout: the dd follows a "Method" dt, with no data-field.
    row = (
        "<table><tr><th>House 1</th><td><p>12 households, estimated from ZIP codes</p>"
        f"<dl><dt>Method</dt><dd>{zip_method}</dd></dl></td></tr>"
        "<tr><th>State</th><td><p>99 households, estimated from ZIP codes</p>"
        "<dl><dt>Method</dt><dd>published estimate</dd></dl></td></tr></table>"
    )
    assert len(zip_wording_errors(row)) == 1


def test_block_ids_name_their_source(pages: dict[str, str]) -> None:
    blocks: list[Block] = page_blocks({"/": pages["/"]})
    assert any(b.id.startswith("/#") for b in blocks)
    assert any(b.id.startswith(str(ROOT / "app/copy.yaml")) for b in blocks)
