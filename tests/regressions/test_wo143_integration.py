"""WO #196 (step 3 of #143): startup validation, request-aware brief rendering and print rules.

Unknown configuration names and malformed section declarations stop the app at startup with
the valid names. The brief route renders each discovered section in isolation: a raising
flagged section is left out (a failure note shows only in preview) and the rest still arrive
with 200. Sections that are not on the printout show a screen-only note and are absent in
print; with every printable section on, House 22 prints on one Letter page.
"""

import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from playwright.sync_api import Page

import app.copy
from app import features
from app.main import app as asgi_app
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page, page

# Reuse the WO122 server and Chromium fixtures without modifying their source.
__all__ = ["base_url", "browser", "page"]

ROOT = Path(__file__).resolve().parents[2]
COPY = yaml.safe_load(app.copy.COPY_PATH.read_text(encoding="utf-8"))
FAILED = COPY["brief"]["section_failed"]
SCREEN_ONLY = COPY["brief"]["screen_only"]

Plant = Callable[..., str]


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "features.toml"
    path.write_text('outreach = "on"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    # Planted declarations must not outlive the test in the process-wide registry.
    monkeypatch.setattr(features, "VALID_NAMES", set(features.VALID_NAMES))
    return path


@pytest.fixture
def client(config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "absent.db"))
    return TestClient(asgi_app)


@pytest.fixture
def plant() -> Iterator[Plant]:
    """Write a temporary section module and template; removed (and unimported) afterwards."""
    planted: list[tuple[Path, Path, str]] = []

    def write(order: str, name: str, header: str = "", body: str = "", raises: bool = False) -> str:
        module = ROOT / f"app/sections/{order}_{name}.py"
        template = ROOT / f"templates/sections/{order}-{name.replace('_', '-')}.html"
        assert not module.exists() and not template.exists()
        marker = f"{name}-marker"
        lines = [
            '"""Planted by a WO196 test."""\n',
            header,
            "from app.page_state import PageState\n",
        ]
        lines.append("\n\ndef context(state: PageState) -> dict[str, object]:\n")
        lines.append('    raise RuntimeError("planted")\n' if raises else "    return {}\n")
        module.write_text("".join(lines))
        template.write_text(f'<section class="planted"><p class="{marker}">{body}</p></section>\n')
        planted.append((module, template, f"app.sections.{order}_{name}"))
        return marker

    yield write
    for module, template, imported in planted:
        module.unlink()
        template.unlink()
        sys.modules.pop(imported, None)


def brief_html(client: TestClient, query: str = "") -> str:
    response = client.get("/brief/house/22" + query)
    assert response.status_code == 200
    return response.text


# --- startup validation ---


def test_startup_accepts_the_shipped_configuration(client: TestClient) -> None:
    with client:
        assert client.get("/healthz").status_code == 200


def test_unknown_configuration_name_fails_startup_listing_valid_names(
    client: TestClient, config: Path
) -> None:
    config.write_text('outreach = "on"\noutrecha = "on"\n')
    unknown = r"Unknown feature 'outrecha'; valid names: .*outreach"
    with pytest.raises(ValueError, match=unknown), client:
        pass


def test_configuration_naming_a_section_flag_passes_startup(
    client: TestClient, config: Path, plant: Plant
) -> None:
    # Section declarations are registered before the configuration is checked.
    plant("25", "wo196_declared", header='FEATURE = "wo196_declared"\n')
    config.write_text('outreach = "on"\nwo196_declared = "preview"\n')
    with client:
        assert client.get("/healthz").status_code == 200


def test_malformed_section_flag_name_fails_startup(client: TestClient, plant: Plant) -> None:
    plant("25", "wo196_badname", header='FEATURE = "Bad-Name"\n')
    with pytest.raises(ValueError, match=r"Invalid feature name 'Bad-Name'"), client:
        pass


def test_section_without_template_fails_startup(client: TestClient, plant: Plant) -> None:
    plant("25", "wo196_orphan")
    template = ROOT / "templates/sections/25-wo196-orphan.html"
    aside = template.with_suffix(".wo196")
    template.rename(aside)
    try:
        with pytest.raises(ValueError, match=r"sections/25-wo196-orphan\.html"), client:
            pass
    finally:
        aside.rename(template)


# --- the brief route ---


def test_all_off_house_22_keeps_headline_figures_programs_order(
    client: TestClient, config: Path
) -> None:
    config.write_text('outreach = "off"\n')
    html = brief_html(client)
    programs = COPY["sections"]["programs"]["heading"]
    assert html.index("<h1") < html.index('class="figure"') < html.index(programs)
    assert 'class="outreach"' not in html
    assert "screen-only" not in html and "section-failure" not in html


@pytest.mark.parametrize(
    "status,query", [("on", ""), ("on", "?preview=1"), ("preview", "?preview=1")]
)
def test_raising_flagged_section_is_contained(
    client: TestClient, config: Path, plant: Plant, status: str, query: str
) -> None:
    marker = plant("25", "wo196_broken", header='FEATURE = "wo196_broken"\n', raises=True)
    config.write_text(f'outreach = "on"\nwo196_broken = "{status}"\n')
    html = brief_html(client, query)
    assert marker not in html
    programs = COPY["sections"]["programs"]["heading"]
    assert html.index("<h1") < html.index('class="figure"') < html.index(programs)
    note = FAILED.format(name="wo196 broken")
    assert (note in html) is (query == "?preview=1")


def test_raising_unflagged_section_still_fails_the_request(
    client: TestClient, plant: Plant
) -> None:
    plant("25", "wo196_core_broken", raises=True)
    with pytest.raises(RuntimeError, match="planted"):
        client.get("/brief/house/22")


@pytest.mark.parametrize(
    "status,query,shown",
    [("preview", "", False), ("preview", "?preview=1", True), ("off", "?preview=1", False)],
)
def test_preview_status_shows_section_only_in_preview(
    client: TestClient, config: Path, plant: Plant, status: str, query: str, shown: bool
) -> None:
    marker = plant("25", "wo196_preview", header='FEATURE = "wo196_preview"\nPRINT = True\n')
    config.write_text(f'outreach = "on"\nwo196_preview = "{status}"\n')
    assert (marker in brief_html(client, query)) is shown


@pytest.mark.parametrize("value", ["yes", "true", "2", ""])
def test_unknown_preview_value_is_404(client: TestClient, value: str) -> None:
    assert client.get(f"/brief/house/22?preview={value}").status_code == 404


def test_preview_zero_is_the_normal_page(client: TestClient) -> None:
    assert client.get("/brief/house/22?preview=0").status_code == 200


@pytest.mark.parametrize(
    "header,screen_only",
    [
        ('FEATURE = "wo196_part"\n', True),
        ('FEATURE = "wo196_part"\nPRINT = False\n', True),
        ('FEATURE = "wo196_part"\nPRINT = True\n', False),
        ("PRINT = False\n", True),
        ("", False),
    ],
)
def test_screen_only_sections_carry_the_note(
    client: TestClient, config: Path, plant: Plant, header: str, screen_only: bool
) -> None:
    marker = plant("25", "wo196_part", header=header)
    config.write_text(
        'outreach = "on"\nwo196_part = "on"\n' if "FEATURE" in header else 'outreach = "on"\n'
    )
    html = brief_html(client)
    assert marker in html
    assert (SCREEN_ONLY in html) is screen_only
    assert ('class="screen-only"' in html) is screen_only


def test_notes_are_worded_in_copy_and_styled_with_tokens() -> None:
    site = (ROOT / "static/site.css").read_text()
    tokens = (ROOT / "static/tokens.css").read_text()
    assert "{name}" in FAILED and SCREEN_ONLY == "Not on the printout"
    for selector in (".screen-only-note", ".section-failure"):
        rule = re.search(re.escape(selector) + r"[^{]*\{(?P<body>[^}]*)\}", site)
        assert rule is not None, selector
        used = re.findall(r"var\((--note-[\w-]+)\)", rule["body"])
        assert used and all(re.search(re.escape(v) + r"\s*:", tokens) for v in used)


# --- in a real browser ---


def pdf_pages(page: Page) -> int:
    """Pages Chromium prints for the open page, using the site's own @page size and margins."""
    pdf = page.pdf(prefer_css_page_size=True)
    boxes = re.findall(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", pdf)
    assert boxes and all((float(w), float(h)) == (612, 792) for w, h in boxes), boxes  # Letter
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


@pytest.fixture
def live_config(config: Path) -> Path:
    """The WO122 server runs in this process, so the patched policy path applies to it."""
    return config


@pytest.mark.parametrize(
    "header,printed",
    [('FEATURE = "wo196_print"\n', False), ('FEATURE = "wo196_print"\nPRINT = True\n', True)],
)
def test_print_excludes_flagged_sections_by_default(
    page: Page, base_url: str, live_config: Path, plant: Plant, header: str, printed: bool
) -> None:
    marker = plant("25", "wo196_print", header=header, body="planted")
    live_config.write_text('outreach = "on"\nwo196_print = "on"\n')
    open_page(page, base_url + "/brief/house/22", 1440)
    section = page.locator(f".{marker}")
    note = page.get_by_text(SCREEN_ONLY, exact=True)
    assert section.is_visible()
    assert note.count() == (0 if printed else 1)
    if not printed:
        assert note.is_visible()
    page.emulate_media(media="print")
    assert section.is_visible() is printed
    assert note.count() == 0 or not note.is_visible()


def test_preview_failure_note_is_on_screen_not_in_print(
    page: Page, base_url: str, live_config: Path, plant: Plant
) -> None:
    plant("25", "wo196_fails", header='FEATURE = "wo196_fails"\n', raises=True)
    live_config.write_text('outreach = "on"\nwo196_fails = "preview"\n')
    open_page(page, base_url + "/brief/house/22?preview=1", 1440)
    note = page.get_by_text(FAILED.format(name="wo196 fails"), exact=True)
    assert note.is_visible()
    page.emulate_media(media="print")
    assert not note.is_visible()


@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
def test_house_22_with_every_printable_section_prints_on_one_letter_page(
    page: Page, base_url: str, live_config: Path, variant: str
) -> None:
    open_page(page, base_url + "/brief/house/22" + variant, 1440)
    assert page.locator(".outreach").count() == 1
    assert pdf_pages(page) == 1


def test_planted_overflow_fails_the_one_page_check(
    page: Page, base_url: str, live_config: Path, plant: Plant
) -> None:
    filler = " ".join(["Planted filler paragraph text."] * 400)
    plant("25", "wo196_tall", header='FEATURE = "wo196_tall"\nPRINT = True\n', body=filler)
    live_config.write_text('outreach = "on"\nwo196_tall = "on"\n')
    open_page(page, base_url + "/brief/house/22", 1440)
    assert pdf_pages(page) > 1
