"""#222: ranked brief and permalink cards share complete evidence and print policy."""

import sqlite3
from importlib import import_module
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app import features
from app.main import app
from app.tools.matches import DistrictMatches
from etl.boundaries import DistrictId
from etl.programs import load_catalog
from etl.programs.mappings import load_mappings
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import axe_problems, browser, page
from tests.regressions.test_wo143_integration import pdf_pages
from tests.regressions.test_wo149_matches import matching_store

__all__ = ["browser", "matching_store", "page"]
ROOT = Path(__file__).resolve().parents[2]


def dom(node: Node) -> tuple[object, ...]:
    """Compare every element, attribute and text, ignoring indentation only."""
    return node.tag, node.attrs, node.text, tuple(dom(child) for child in node.children)


@pytest.mark.parametrize("chamber", ["house", "senate"])
@pytest.mark.parametrize("evidence", ["available", "missing", "caution"])
def test_complete_brief_card_matches_permalink(
    matching_store: Path, chamber: Literal["house", "senate"], evidence: str
) -> None:
    with sqlite3.connect(matching_store) as db:
        if evidence == "missing":
            db.execute("DELETE FROM facts WHERE variable LIKE 'S1810%'")
        elif evidence == "caution":
            db.execute(
                "UPDATE facts SET moe = NULL, cv = NULL, reliability = 'caution' "
                "WHERE variable LIKE 'S1810%'"
            )
        else:
            db.execute(
                "UPDATE facts SET value = 1234, moe = 234, cv = 0.115, "
                "reliability = 'reliable' WHERE variable = 'S1810_C02_001E'"
            )
    client = TestClient(app)
    response = client.get(f"/brief/{chamber}/22?preview=1")
    assert response.status_code == 200
    brief = parse(response.text).one("section", class_="matches")
    matches = DistrictMatches(DistrictId(chamber=chamber, district=22)).get_matches()
    for match in matches:
        population, program = match.population, match.program
        identity = f"{match.count.geography}:{population.id}:{program.id}"
        card = brief.one("article", data_match=identity)
        permalink = client.get(f"/match/{chamber}/22/{program.id}/{population.id}?preview=1")
        assert permalink.status_code == 200
        assert dom(card) == dom(parse(permalink.text).one("article", data_match=identity))
        figure = card.one("div", data_match=f"{population.id}:{program.id}")
        assert "Survey population:" in figure.text
        assert population.label in figure.text
        assert population.definition in figure.text
        assert population.universe in figure.text
        assert "Comparable uptake unavailable" in card.text
        assert "agency decides eligibility" in card.text
        links = {a.attrs["href"] for a in card.find_all("a")}
        assert str(program.official_url) in links
        assert program.referral_url in links
        if program.next_steps:
            assert str(program.next_steps.contact.url) in links
        if population.id == "disability":
            if evidence == "missing":
                assert "Not available" in figure.text
                assert "S1810_C02_001E" in figure.text
                assert "insufficient" in card.text
            elif evidence == "caution":
                assert "use with caution" in figure.text
                assert "Margin of error unavailable" in figure.text
            else:
                assert "1,234 persons" in figure.text
                assert "±234" in figure.text


def test_rendered_order_preserves_tool_ranking(matching_store: Path) -> None:
    # Available SNAP/ABLE evidence and missing other populations yield distinct scores.
    mappings = load_mappings()
    matches = DistrictMatches(DistrictId(chamber="house", district=22)).get_matches(mappings)
    assert len({m.result.score for m in matches}) > 1
    ordered = [(m.population.id, m.program.id) for m in matches]
    assert ordered != [(m.population_id, m.program_id) for m in mappings]
    section = parse(TestClient(app).get("/brief/house/22?preview=1").text).one(
        "section", class_="matches"
    )
    assert [a.attrs["data-match"] for a in section.find_all("article")] == [
        f"{m.count.geography}:{m.population.id}:{m.program.id}" for m in matches
    ]


def test_flag_off_preserves_catalog_without_loading_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matching_store: Path
) -> None:
    client = TestClient(app)
    enabled = parse(client.get("/brief/house/22?preview=1").text).one("section", class_="programs")
    config = tmp_path / "off.toml"
    config.write_text('outreach = "on"\nmatches = "off"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", config)

    def no_load() -> None:
        raise AssertionError("flag-off matches must not load mappings")

    monkeypatch.setattr(import_module("app.sections.36_matches"), "load_mappings", no_load)
    response = client.get("/brief/house/22?preview=1")
    assert response.status_code == 200
    tree = parse(response.text)
    assert not tree.find_all("section", class_="matches")
    catalog = tree.one("section", class_="programs")
    assert dom(catalog) == dom(enabled)
    assert len(catalog.find_all("li")) == len(load_catalog(ROOT / "data/programs.yaml"))
    assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("width", [390, 768, 1440])
def test_accessible_cards_preserve_brief_and_permalink_print_policy(
    page: Page, width: int, monkeypatch: pytest.MonkeyPatch, matching_store: Path
) -> None:
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    client = TestClient(app)
    page.set_viewport_size({"width": width, "height": 900})
    for path in (
        "/brief/house/22?preview=1",
        "/match/house/22/snap/below_poverty_no_snap?preview=1",
    ):
        monkeypatch.setenv(
            "KYD_FACTS_DB",
            str(ROOT / "data/facts.db") if path.startswith("/brief") else str(matching_store),
        )
        response = client.get(path)
        assert response.status_code == 200
        page.emulate_media(media="screen")
        page.set_content(response.text)
        for stylesheet in ("tokens.css", "site.css"):
            page.add_style_tag(path=str(ROOT / "static" / stylesheet))
        assert axe_problems(page) == []
        if path.startswith("/brief"):
            cards = page.locator(".matches article")
            assert cards.count() > 0
            assert all(card.is_visible() for card in cards.all())
            page.emulate_media(media="print")
            assert all(not card.is_visible() for card in cards.all())
            assert pdf_pages(page) == 1
        else:
            page.emulate_media(media="print")
            assert page.locator("article.case").is_visible()
            citations = page.locator(".case-citation")
            assert citations.count() > 0
            assert all(citation.is_visible() for citation in citations.all())
