"""WO187: every page string reads at grade 8 or below, and method words stay true.

The rule (docs/plain-language.md, "Page rule"): citation fields stay excluded
exactly as before; fixed names become a placeholder; a 1–3 word label has no word
over three syllables; every other string scores Flesch–Kincaid grade 8 or lower.
"""

from html import escape, unescape
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
from tests.regressions.test_wo97_brief_page import parse

ROOT = Path(__file__).resolve().parents[2]
ZIP_WORDS = "estimated from zip codes"


@pytest.fixture(scope="session")
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


def test_saved_case_and_match_pages_are_scored(pages: dict[str, str]) -> None:
    for path in (
        "fixture:folder",
        "fixture:folder?matches=1",
        "fixture:folder-populations",
        "fixture:folder-populations?matches=1",
    ):
        assert path in pages
        page = parse(pages[path])
        if path.endswith("?matches=1"):
            assert page.find_all("section", id="missing-matches")
            assert page.find_all("div", class_="folder-suggestion")
        else:
            assert page.find_all("section", class_="case")
            assert page.find_all("article", class_="case")
        assert "The agency decides eligibility." in page.text
        assert page.find_all("a", href="https://www.auw211.org/")
        failures = hard_blocks(page_blocks({path: pages[path]}))
        assert not failures, [(b.text, r.grade, r.long_words) for b, r in failures]


def test_match_card_labels_read_plainly_and_track_the_opening_case() -> None:
    from app.copy import section_copy
    from app.match_cards import ACTIONS, CLAIMS, GAPS, CardWording
    from app.program_cards import ProgramCardWording
    from scripts.readability_corpus import check_reading

    words = section_copy("case")
    assert words["gaps"] == GAPS
    assert words["actions"] == ACTIONS
    for text in (
        *CLAIMS.values(),
        *CardWording().model_dump().values(),
        *ProgramCardWording().model_dump().values(),
    ):
        assert check_reading(text).ok, text


def test_match_copy_keeps_survey_and_agency_limits() -> None:
    from app.populations import load_populations
    from etl.programs.mappings import load_mappings

    population = next(p for p in load_populations().populations if p.id == "below_poverty_no_snap")
    assert population.numerator == ("B22003_006E",)
    assert population.denominator == ("B22003_003E", "B22003_006E")
    assert population.unit == "households"
    assert population.universe == "Households"
    assert "12 months" in population.definition
    assert "survey misses some receipt" in population.definition
    assert "does not prove unmet need" in population.definition
    mapping = next(m for m in load_mappings() if m.program_id == "snap")
    assert mapping.claim == "relevant_need"
    assert mapping.review_status == "pending"
    assert mapping.modeling_evidence is mapping.comparability_evidence is None
    assert "The agency decides eligibility." in mapping.relevance
    assert "does not count those who meet the rules but lack aid" in mapping.relevance
    assert "Aloha United Way 211" in mapping.relevance
    unknown = " ".join(mapping.unobserved_conditions)
    for limit in (
        "Current income",
        "deduct",
        "SNAP household",
        "Rules beyond income",
        "gets SNAP now",
        "misses some past receipt",
    ):
        assert limit in unknown


# --- Match permalinks, ranked preview cards and saved folder cards ---

STORES = ("fixture:brief-store", "fixture:population-store")


def _shipped() -> list[tuple[str, str]]:
    from etl.programs.mappings import load_mappings

    return [
        (m.population_id, m.program_id) for m in load_mappings() if m.review_status != "rejected"
    ]


def test_corpus_renders_every_shipped_mapping_on_its_permalink(pages: dict[str, str]) -> None:
    from scripts.readability_corpus import MATCH_DISTRICTS

    shipped = _shipped()
    assert {program for _, program in shipped} >= {"snap", "hawaii-able", "public-pre-k"}
    assert {c for c, _ in MATCH_DISTRICTS} == {"house", "senate"}
    for store in STORES:
        for chamber, n in MATCH_DISTRICTS:
            for population, program in shipped:
                page = pages[f"{store}:/match/{chamber}/{n}/{program}/{population}?preview=1"]
                assert f':{population}:{program}"' in page  # the rendered card itself
        for chamber, n in MATCH_DISTRICTS[:2]:
            page = pages[f"{store}:/brief/{chamber}/{n}?preview=1"]
            for population, program in shipped:
                assert f':{population}:{program}"' in page
    for name in ("fixture:folder-all", "fixture:folder-populations-all"):
        for population, program in shipped:
            assert f'data-match="{population}:{program}"' in pages[name]


def test_every_match_card_block_reads_at_grade_8_or_below(pages: dict[str, str]) -> None:
    sources = [p for p in pages if p.startswith(STORES) or p.startswith("fixture:folder")]
    assert len(sources) >= 2 * (6 * 3 + 2) + 8
    blocks = [b for p in sources for b in rendered_blocks(pages[p], p)]
    failed = [(b.id, r.grade, r.long_words, b.text) for b, r in hard_blocks(blocks)]
    assert failed == []


@pytest.mark.parametrize(
    "old",
    [
        # Strings the reviewer reproduced on match pages, and their siblings.
        "Households below poverty reporting no SNAP · Supplemental Nutrition Assistance "
        "Program (SNAP)",
        "Active-duty military and institutional residents are excluded.",
        "Residents aged 5 and over are excluded from the numerator.",
        "Hawaiʻi ABLE may help people with disabilities save for disability-related expenses. "
        "This survey-defined population is a potential outreach audience, not an estimate of "
        "eligibility or nonparticipation. Program-expert review is pending; the agency decides "
        "eligibility.",
        "Review the official program information; this savings program may help, and the "
        "agency decides eligibility.",
        "Review the dated official FAQ and linked application portal; the agency decides "
        "eligibility.",
        "Ranked population connections to programs",
        "house:15:022:2022 · Civilian noninstitutionalized population · published estimate "
        "and 90% margin of error",
    ],
)
def test_restoring_old_match_prose_fails(old: str) -> None:
    assert not check_reading(old).ok


def _article(page: str, population: str, program: str) -> str:
    return page.split(f':{population}:{program}"', 1)[1].split("</article>", 1)[0]


def test_match_permalink_keeps_figures_citations_and_safeguards(pages: dict[str, str]) -> None:
    from app.populations import load_populations
    from etl.programs import load_catalog

    populations = {p.id: p for p in load_populations().populations}
    catalog = {p.id: p for p in load_catalog(ROOT / "data/programs.yaml")}
    for population, program in _shipped():
        p, record = populations[population], catalog[program]
        for store in STORES:
            page = pages[f"{store}:/match/house/22/{program}/{population}?preview=1"]
            heading = f"Who to reach: {p.label}. What may help: {record.name}."
            assert f"<h1>{escape(heading, quote=False)}</h1>" in page
            article = _article(page, population, program)
            text = unescape(article)
            # The universe and geography code stay on the card; the code is a cited field.
            assert f"Who is in the count: {p.universe}." in text
            assert '<code data-field="geography">house:15:022:2022</code>' in article
            assert "How we got this number:" in text
            assert p.definition in text and all(e in text for e in p.exclusions)
            assert "The agency decides eligibility." in text
            assert str(record.official_url) in article
            assert "https://www.auw211.org/" in article
            # The card's count cites each numerator cell, as an input or as missing.
            assert all(cell in text for cell in p.numerator)
            if store == "fixture:population-store":
                assert "2020–2024" in text and "±" in text
            if len(p.numerator) > 1:
                assert f"derived: sum of {len(p.numerator)} published estimates. MOE sqrt(" in text
            assert "estimates; MOE" not in text


def test_rewritten_match_records_keep_every_fact_and_limit() -> None:
    from app.populations import load_populations
    from etl.programs import load_catalog
    from etl.programs.mappings import load_mappings

    populations = {p.id: p for p in load_populations().populations}
    disability, under5 = populations["disability"], populations["children_under_5"]
    assert disability.universe == "Civilian noninstitutionalized population"
    assert disability.numerator == ("S1810_C02_001E",)
    assert disability.denominator == ("S1810_C01_001E",)
    assert (disability.unit, disability.period) == ("persons", "survey_time")
    limits = disability.definition + " " + " ".join(disability.exclusions)
    for words in ("said they have a disability", "active", "prisons or nursing homes"):
        assert words in limits
    assert under5.universe == "Total population"
    assert under5.numerator == ("B01001_003E", "B01001_027E")
    assert under5.denominator == ("B01001_001E",)
    assert under5.exclusions == (
        "People age 5 and older are not in the count of children. They are in the total.",
    )
    mappings = {m.program_id: m for m in load_mappings()}
    able, prek = mappings["hawaii-able"], mappings["public-pre-k"]
    for mapping in (able, prek):
        assert mapping.claim == "relevant_need" and mapping.review_status == "pending"
        assert mapping.modeling_evidence is mapping.comparability_evidence is None
        assert "The agency decides eligibility." in mapping.relevance
        assert "who meets the rules" in mapping.relevance
        for text in (
            mapping.relevance,
            *mapping.observed_conditions,
            *mapping.unobserved_conditions,
        ):
            assert check_reading(text).ok, text
    assert "who lacks aid" in able.relevance
    unknown = " ".join(able.unobserved_conditions)
    for limit in (
        "Disability onset",
        "age limit",
        "certification",
        "account",
        "benefits affect",
        "enrollment",
        "fees",
        "incentives",
        "not checked",
    ):
        assert limit in unknown
    assert "who is not enrolled" in prek.relevance and "Aloha United Way 211" in prek.relevance
    unknown = " ".join(prek.unobserved_conditions)
    for limit in (
        "birth date",
        "priority",
        "schools take part",
        "schedule",
        "before or after school",
        "seats are open",
        "enrolled now",
    ):
        assert limit in unknown
    # Three conditions, each its own string (a comma must not split one in two).
    assert len(prek.unobserved_conditions) == 3
    catalog = {p.id: p for p in load_catalog(ROOT / "data/programs.yaml")}
    for program in ("hawaii-able", "public-pre-k"):
        steps = catalog[program].next_steps
        assert steps is not None and str(steps.contact.url) == "https://www.auw211.org/"
        assert "The agency decides eligibility." in steps.instructions[0]
        assert all(check_reading(step).ok for step in steps.instructions)
    able_steps = catalog["hawaii-able"].next_steps
    assert able_steps is not None
    assert "Aloha United Way 211" in able_steps.instructions[1]
    assert "not checked" in able_steps.instructions[1]
    assert "before you plan outreach" in able_steps.instructions[2]
