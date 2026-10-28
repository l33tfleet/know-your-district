"""WO #128: every brief lists the programs that may help, from `data/programs.yaml`.

Each program shows its name, agency, 'may help' purpose and a link to its official page,
the line that the agency decides eligibility and a link to Aloha United Way 211. The
section shows no number from the catalog and never says 'qualify' or 'eligible for'.
"""

import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from tests.regressions.test_wo97_brief_page import ROWS, Node, Tree, build_db

ROOT = Path(__file__).resolve().parents[2]
REFERRAL = "https://www.auw211.org/"
PAGES = ("/brief/house/19", "/brief/house/22", "/brief/senate/5", "/brief/senate/25")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "facts.db"
    build_db(path, ROWS)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return TestClient(app)


def catalog() -> list[dict[str, object]]:
    raw: list[dict[str, object]] = yaml.safe_load(
        (ROOT / "data/programs.yaml").read_text(encoding="utf-8")
    )
    return raw


def section_of(html: str) -> Node:
    tree = Tree()
    tree.feed(html)
    return tree.root.one("section", class_="programs")


@pytest.mark.parametrize("path", PAGES)
def test_programs_section_lists_snap_and_ga_with_official_and_211_links(
    client: TestClient, path: str
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    section = section_of(response.text)
    assert section.one("h2").text == "Programs that may help"
    items = section.find_all("li")
    names = [p["name"] for p in catalog()]
    assert "Supplemental Nutrition Assistance Program (SNAP)" in names
    assert "General Assistance (GA)" in names
    assert len(items) == len(names)
    for item, program in zip(items, catalog(), strict=True):
        text = item.text
        for key in ("name", "agency", "purpose", "guidance"):
            assert str(program[key]) in text, (key, text)
        assert "agency decides eligibility" in text.casefold()
        hrefs = [a.attrs.get("href") for a in item.find_all("a")]
        assert program["official_url"] in hrefs
        assert REFERRAL in hrefs
        assert program["referral_url"] == REFERRAL
        links = {a.attrs["href"]: a.text for a in item.find_all("a")}
        assert links[str(program["official_url"])] == "Official program page"
        assert links[REFERRAL] == "Aloha United Way 211"


def test_programs_section_comes_after_the_figures(client: TestClient) -> None:
    html = client.get("/brief/house/19").text
    assert html.rindex('class="figure"') < html.index('class="programs"')


@pytest.mark.parametrize("path", PAGES)
def test_programs_section_never_says_you_qualify_and_shows_no_catalog_number(
    client: TestClient, path: str
) -> None:
    html = client.get(path).text
    assert "qualify" not in html.casefold()
    assert "eligible for" not in html.casefold()
    text = section_of(html).text.casefold()
    # No counts, thresholds, proxies or dates from the catalog: the visible text has no digits
    # except the "211" in the referral line.
    assert re.findall(r"\d+", text.replace("211", "")) == []
