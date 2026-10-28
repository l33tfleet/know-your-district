"""WO #97: the brief's structure. Wording lives only in `app/copy.yaml`, visual values only
in the tokens CSS file, and a section is two new files (`app/sections/NN_name.py` and
`templates/sections/NN-name.html`) found by prefix, with no central list to edit."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.copy
from app.main import app as asgi_app

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\b(?:black|white|gr[ae]y|red)\b")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "absent.db"))
    return TestClient(asgi_app)


def page_templates() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html"))


def test_templates_hold_no_wording() -> None:
    """Strip Jinja tags, HTML tags and entities; no letters may remain."""
    for path in page_templates():
        source = path.read_text()
        source = re.sub(r"{#.*?#}|{%.*?%}|{{.*?}}", " ", source, flags=re.S)
        source = re.sub(r"<!--.*?-->|<[^>]*>|&[a-z]+;", " ", source, flags=re.S)
        assert not re.search(r"[^\W\d_]", source), (path, source.split())


def test_templates_hold_no_inline_style_or_colour() -> None:
    for path in page_templates():
        source = path.read_text()
        assert "style=" not in source and "<style" not in source, path
        assert not COLOUR.search(source), path


def test_site_css_takes_every_visual_value_from_tokens() -> None:
    tokens = (ROOT / "static/tokens.css").read_text()
    site = (ROOT / "static/site.css").read_text()
    defined = set(re.findall(r"(--[\w-]+)\s*:", tokens))
    used = set(re.findall(r"var\((--[\w-]+)\)", site))
    assert used and used <= defined
    assert not COLOUR.search(re.sub(r"/\*.*?\*/", "", site, flags=re.S))
    assert not re.search(r"\d(?:px|rem|em|pt|%)", re.sub(r"/\*.*?\*/", "", site, flags=re.S))


def test_pages_load_tokens_before_site_css(client: TestClient) -> None:
    for path in ("/", "/brief/house/22"):
        html = client.get(path).text
        assert html.index('href="/static/tokens.css"') < html.index('href="/static/site.css"')


def test_changing_a_token_changes_the_served_page_style(client: TestClient) -> None:
    tokens = ROOT / "static/tokens.css"
    original = tokens.read_text()
    assert "--color-text:" in original
    changed = re.sub(r"--color-text:[^;]*;", "--color-text: #123456;", original, count=1)
    try:
        tokens.write_text(changed)
        assert "#123456" in client.get("/static/tokens.css").text
    finally:
        tokens.write_text(original)


def test_copy_is_grouped_by_section() -> None:
    copy = yaml.safe_load(app.copy.COPY_PATH.read_text())
    assert {"site", "home", "not_found", "sections"} <= set(copy)
    assert {"headline", "figures"} <= set(copy["sections"])


@pytest.mark.parametrize(
    ("path", "group", "key"),
    [
        ("/", "home", "intro"),
        ("/brief/house/22", "sections", "figures"),
        ("/brief/house/22", "site", "footer"),
        ("/no-such-page", "not_found", "heading"),
    ],
)
def test_changing_copy_changes_the_page(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    group: str,
    key: str,
) -> None:
    copy = yaml.safe_load(app.copy.COPY_PATH.read_text())
    marker = "Wo97 marker string"
    if group == "sections":
        copy["sections"][key]["source_summary"] = marker
    else:
        copy[group][key] = marker
    assert marker not in client.get(path).text
    edited = tmp_path / "copy.yaml"
    edited.write_text(yaml.safe_dump(copy, allow_unicode=True))
    monkeypatch.setattr(app.copy, "COPY_PATH", edited)
    assert marker in client.get(path).text


@pytest.fixture
def dummy_section() -> Iterator[str]:
    module = ROOT / "app/sections/15_wo97_dummy.py"
    template = ROOT / "templates/sections/15-wo97-dummy.html"
    assert not module.exists() and not template.exists()
    module.write_text(
        '"""Dummy section added by a WO97 test."""\n\n'
        "from app.page_state import PageState\n\n\n"
        "def context(state: PageState) -> dict[str, object]:\n"
        '    return {"marker": f"wo97-dummy-{state.district.key}"}\n'
    )
    template.write_text('<p class="wo97-dummy">{{ section.marker }}</p>\n')
    try:
        yield "wo97-dummy-house-22"
    finally:
        module.unlink()
        template.unlink()


def test_adding_a_section_is_two_new_files(client: TestClient, dummy_section: str) -> None:
    html = client.get("/brief/house/22").text
    assert dummy_section in html
    # Ordered by prefix: 10 headline, 15 dummy, 20 figures.
    assert html.index("<h1") < html.index(dummy_section) < html.index('class="figure"')


def test_sections_render_in_prefix_order_without_dummy(client: TestClient) -> None:
    html = client.get("/brief/house/22").text
    assert "wo97-dummy" not in html
    assert html.index("<h1") < html.index('class="figure"')
