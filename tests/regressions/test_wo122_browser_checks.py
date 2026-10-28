"""WO #122: `/` and `/brief/house/22` in a real browser at 390, 768 and 1440 px.

Each page must have no serious or critical axe-core violations, every figure's source
`<details>` must be reachable and openable by keyboard, every Hawaiian place name must use the
ʻokina (U+02BB) and kahakō, and choosing a district via the picker must not reload the page.
The `test_planted_*` cases plant one defect each and show that its check catches it.

Runs headless Chromium through Playwright (`uv run playwright install chromium`, done by
`make check`) against uvicorn serving a synthetic fixture database. axe-core is the copy pinned
in uv.lock through the `axe-playwright-python` package; only its `axe.min.js` is used.
"""

import os
import re
import socket
import sqlite3
import threading
import time
from collections.abc import Iterator
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

from app.analysis.reliability import classify
from app.main import app
from app.models import Fact

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (390, 768, 1440)
PAGES = ("/", "/brief/house/22")
HOUSE_22 = "house:15:022:2022"
STATE = "state:15"
DETAILED = "https://api.census.gov/data/2024/acs/acs5"
PROFILE = "https://api.census.gov/data/2024/acs/acs5/profile"
VARIABLES = {
    "B01003_001E": ("B01003", DETAILED),
    "DP05_0024PE": ("DP05", PROFILE),
    "B19013_001E": ("B19013", DETAILED),
}
AXE_JS = (files("axe_playwright_python") / "axe.min.js").read_text(encoding="utf-8")

# Correct spelling of each Hawaiian place name (AGENTS.md rule 6).
PLACE_NAMES = ("Hawaiʻi", "Kauaʻi", "Lānaʻi", "Molokaʻi", "Oʻahu", "Kahoʻolawe", "Niʻihau")
# The ʻokina and what gets typed in its place: apostrophe, left/right quote, grave, acute.
OKINA_LOOKALIKES = "ʻ'\u2018\u2019`\u00b4"
MACRONS = {"ā": "a", "ē": "e", "ī": "i", "ō": "o", "ū": "u"}


def row(variable: str, geography: str, value: float, moe: float | None) -> Fact:
    """A synthetic fact, never a published observation."""
    table_id, endpoint = VARIABLES[variable]
    cv, reliability = classify(
        Decimal(repr(value)), Decimal(repr(moe)) if moe is not None else None
    )
    return Fact(
        variable=variable,
        geography=geography,
        vintage="2020–2024",
        value=value,
        moe=moe,
        cv=float(cv) if cv is not None else None,
        reliability=reliability,
        source="U.S. Census Bureau ACS 5-year (synthetic test row)",
        table_id=table_id,
        method="published estimate and 90% margin of error"
        + ("; MOE controlled" if moe is None else ""),
        endpoint=endpoint,
        label=f"Synthetic label for {variable}",
    )


ROWS = [
    row("B01003_001E", HOUSE_22, 23456.0, 1234.0),
    row("DP05_0024PE", HOUSE_22, 21.3, 2.1),
    row("B19013_001E", HOUSE_22, 98765.0, 30000.0),
    row("B01003_001E", STATE, 1446146.0, None),
    row("DP05_0024PE", STATE, 19.8, 0.1),
    row("B19013_001E", STATE, 95322.0, 612.0),
]


def build_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        columns = list(Fact.model_fields)
        db.executemany(
            f"INSERT INTO facts ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [tuple(getattr(r, c) for c in columns) for r in ROWS],
        )
    path.chmod(0o444)


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """uvicorn serving the app on a free local port, reading the fixture database."""
    db = tmp_path_factory.mktemp("wo122") / "facts.db"
    build_db(db)
    previous = os.environ.get("KYD_FACTS_DB")
    os.environ["KYD_FACTS_DB"] = str(db)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if previous is None:
            del os.environ["KYD_FACTS_DB"]
        else:
            os.environ["KYD_FACTS_DB"] = previous


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        chromium = p.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context()
    context.set_default_timeout(10_000)
    yield context.new_page()
    context.close()


def open_page(page: Page, url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(url)
    page.wait_for_load_state("load")


# --- the checks: each returns a list of problems, empty when the page passes ---


def axe_problems(page: Page) -> list[str]:
    """Serious or critical axe-core violations, as `rule-id (impact): target`."""
    page.evaluate(AXE_JS)
    violations: list[dict[str, object]] = page.evaluate(
        "async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
        ".map(v => ({id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target.join(' '))}))"
    )
    return [
        f"{v['id']} ({v['impact']}): {v['targets']}"
        for v in violations
        if v["impact"] in ("serious", "critical")
    ]


def keyboard_problems(page: Page) -> list[str]:
    """Every figure's source `<details>` must take Tab focus and open with Enter."""
    summaries = page.locator(".figure details.source > summary")
    total = summaries.count()
    page.evaluate("document.activeElement && document.activeElement.blur()")
    for _ in range(200):
        page.keyboard.press("Tab")
        focus: str = page.evaluate(
            "(() => { const a = document.activeElement;"
            " if (!a || a === document.body) return 'body';"
            " if (a.dataset.kydSeen) return 'again';"
            " a.dataset.kydSeen = '1';"
            " return a.matches('.figure details.source > summary') ? 'summary' : 'other'; })()"
        )
        if focus == "again":
            break
        if focus == "summary":
            page.keyboard.press("Enter")
            opened: bool = page.evaluate("document.activeElement.parentElement.open")
            page.keyboard.press("Enter")
            if opened:
                page.evaluate("document.activeElement.dataset.kydOpened = '1'")
    problems: list[str] = []
    for i in range(total):
        summary = summaries.nth(i)
        figure = summary.evaluate("s => s.closest('.figure').dataset.figure")
        if summary.get_attribute("data-kyd-seen") is None:
            problems.append(f"source details of {figure} not reachable by Tab")
        elif summary.get_attribute("data-kyd-opened") is None:
            problems.append(f"source details of {figure} does not open with Enter")
    return problems


def misspelling_pattern(name: str) -> re.Pattern[str]:
    """Matches the name with any ʻokina lookalike (or none) and with or without kahakō."""
    parts: list[str] = []
    for ch in name:
        if ch == "ʻ":
            parts.append(f"[{re.escape(OKINA_LOOKALIKES)}]?")
        elif ch in MACRONS:
            parts.append(f"[{ch}{MACRONS[ch]}]")
        else:
            parts.append(re.escape(ch))
    return re.compile(r"\b" + "".join(parts) + r"\b", re.IGNORECASE)


def spelling_problems(text: str) -> list[str]:
    """Hawaiian place names in `text` written without the correct ʻokina or kahakō."""
    return [
        f"{found!r} should be {name!r}"
        for name in PLACE_NAMES
        for found in misspelling_pattern(name).findall(text)
        if found != name
    ]


def page_text(page: Page) -> str:
    """All rendered text, including closed `<details>`, the title and accessible names."""
    return page.evaluate(
        "[document.documentElement.textContent,"
        " ...[...document.querySelectorAll('[aria-label],[title],[alt]')]"
        "   .flatMap(e => ['aria-label', 'title', 'alt'].map(a => e.getAttribute(a) || ''))"
        "].join('\\n')"
    )


def reload_problems(page: Page, base_url: str) -> list[str]:
    """Choose House 22 in the picker on `/`; the brief must arrive without a page reload."""
    page.evaluate("window.kydSameDocument = true")
    page.select_option("#chamber", "house")
    page.wait_for_load_state("networkidle")
    page.select_option("#district-number", "22")
    page.get_by_role("button", name="Open the brief").click()
    page.wait_for_url(f"{base_url}/brief/house/22")
    page.locator("h1", has_text="Hawaiʻi State House District 22").wait_for()
    problems: list[str] = []
    if not page.evaluate("window.kydSameDocument === true"):
        problems.append("choosing a district reloaded the whole page")
    if page.title() != "Hawaiʻi State House District 22 · Know Your District":
        problems.append(f"page title after the picker is {page.title()!r}")
    return problems


# --- the pages pass ---


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("path", PAGES)
def test_no_serious_or_critical_axe_violations(
    page: Page, base_url: str, path: str, width: int
) -> None:
    open_page(page, base_url + path, width)
    assert axe_problems(page) == []


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("path", PAGES)
def test_place_names_spelled_with_okina_and_kahako(
    page: Page, base_url: str, path: str, width: int
) -> None:
    open_page(page, base_url + path, width)
    text = page_text(page)
    assert "Hawaiʻi" in text
    assert spelling_problems(text) == []


@pytest.mark.parametrize("width", WIDTHS)
def test_every_source_details_reachable_by_keyboard(page: Page, base_url: str, width: int) -> None:
    open_page(page, base_url + "/brief/house/22", width)
    assert page.locator(".figure details.source > summary").count() == 3
    assert keyboard_problems(page) == []


@pytest.mark.parametrize("width", WIDTHS)
def test_picker_opens_brief_without_full_reload(page: Page, base_url: str, width: int) -> None:
    open_page(page, base_url + "/", width)
    assert reload_problems(page, base_url) == []


def test_brief_reached_by_picker_passes_the_same_checks(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 390)
    assert reload_problems(page, base_url) == []
    assert axe_problems(page) == []
    assert spelling_problems(page_text(page)) == []
    assert keyboard_problems(page) == []


# --- each planted defect makes its check fail ---


def test_planted_missing_label_fails_axe(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    page.evaluate("document.querySelector('label[for=chamber]').remove()")
    problems = axe_problems(page)
    assert any(p.startswith("select-name (critical): ") and "#chamber" in p for p in problems)


@pytest.mark.parametrize("wrong", ["Hawai'i", "Hawai\u2018i", "Hawaii", "Lanaʻi", "Oahu"])
def test_planted_misspelled_place_name_fails_spelling(
    page: Page, base_url: str, wrong: str
) -> None:
    open_page(page, base_url + "/brief/house/22", 1440)
    page.evaluate("t => { document.querySelector('h1').textContent = t }", f"{wrong} District")
    problems = spelling_problems(page_text(page))
    assert len(problems) == 1
    assert problems[0].startswith(f"{wrong!r} should be ")


def test_planted_full_reload_fails_reload_check(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    # A copy of the form that htmx has not processed submits the browser's way: a full reload.
    page.evaluate(
        "(() => { const f = document.querySelector('form.picker');"
        " const plain = f.cloneNode(true);"
        " for (const e of [plain, ...plain.querySelectorAll('*')])"
        "   for (const a of [...e.attributes]) if (a.name.startsWith('hx-')) e.removeAttribute(a.name);"
        " f.replaceWith(plain); })()"
    )
    assert reload_problems(page, base_url) == ["choosing a district reloaded the whole page"]


def test_planted_untabbable_source_fails_keyboard(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/brief/house/22", 1440)
    page.evaluate("document.querySelector('.figure[data-figure=population] summary').tabIndex = -1")
    assert keyboard_problems(page) == ["source details of population not reachable by Tab"]


def test_planted_summary_that_ignores_enter_fails_keyboard(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/brief/house/22", 1440)
    # Still tabbable, but Enter (which activates the summary as a click) no longer opens it.
    page.evaluate(
        "document.querySelector('.figure[data-figure=population] summary')"
        ".addEventListener('click', e => e.preventDefault())"
    )
    assert keyboard_problems(page) == ["source details of population does not open with Enter"]


def test_planted_wrong_title_after_picker_fails_reload_check(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    # The brief still arrives without a reload, but the swapped-in response has the wrong title.
    page.evaluate(
        "document.addEventListener('htmx:beforeSwap', e => {"
        " e.detail.serverResponse = e.detail.serverResponse.replace("
        "   '<title>Hawaiʻi State House District 22', '<title>Wrong District 22'); })"
    )
    assert reload_problems(page, base_url) == [
        "page title after the picker is 'Wrong District 22 · Know Your District'"
    ]
