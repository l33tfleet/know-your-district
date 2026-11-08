"""#385: programs disclose the same complete evidence card as each permalink."""

import re
import sqlite3
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app import features, program_cards
from app.main import app, templates
from app.program_contacts import ProgramContact
from app.tools.matches import DistrictMatches, ProgramMatch
from etl.boundaries import DistrictId
from etl.programs import load_catalog
from etl.programs.mappings import load_mappings
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, browser, page
from tests.regressions.test_wo143_integration import pdf_pages
from tests.regressions.test_wo149_matches import matching_store
from tests.regressions.test_wo150_prek import complete_store

__all__ = ["browser", "complete_store", "matching_store", "page"]
ROOT = Path(__file__).resolve().parents[2]
DISTRICT = DistrictId(chamber="house", district=22)


@pytest.fixture
def policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "features.toml"
    path.write_text('outreach = "on"\nprogram_cards = "on"\nmatches = "on"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    return path


def complete_articles(markup: str) -> list[str]:
    # Preserve every attribute and all inline text; discard newline indentation only.
    return [
        re.sub(r"\n[ \t]*", "", article)
        for article in re.findall(r'<article class="case"[^>]*>.*?</article>', markup, re.S)
    ]


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_program_cards_match_complete_permalink_dom(
    policy: Path, complete_store: Path, chamber: Literal["house", "senate"]
) -> None:
    with sqlite3.connect(complete_store) as db:
        db.execute(
            "UPDATE facts SET value = 10, cv = 2 / 1.645 / 10 "
            "WHERE geography = 'state:15' AND variable IN ('B22003_006E', 'S1810_C02_001E')"
        )
    district = DistrictId(chamber=chamber, district=22)
    matches = DistrictMatches(district).get_matches()
    strong = [m for m in matches if m.result.band == "strong"]
    assert len(strong) > 1
    assert [(m.population.id, m.program.id) for m in strong] != [
        (m.population_id, m.program_id) for m in load_mappings()
    ]
    client = TestClient(app)
    response = client.get(f"/brief/{chamber}/22")
    assert response.status_code == 200
    programs = parse(response.text).one("section", class_="programs")
    cards = programs.find_all("article", class_="case")
    assert [c.attrs["data-match"] for c in cards] == [
        f"{district.fact_key}:{m.population.id}:{m.program.id}" for m in strong
    ]
    # Extract only the programs section, avoiding the separately flagged matches section.
    markup = response.text.split('<section class="programs">', 1)[1].split("</section>", 1)[0]
    articles = complete_articles(markup)
    assert len(articles) == len(strong)
    for match, card, article in zip(strong, cards, articles, strict=True):
        permalink = client.get(f"/match/{chamber}/22/{match.program.id}/{match.population.id}")
        assert permalink.status_code == 200
        assert [article] == complete_articles(permalink.text)
        assert "data-program-card" not in card.attrs
        figure = card.one("div", class_="case-figure")
        assert f"{match.count.value:,.0f} {match.population.unit}" in figure.text
        assert f"±{match.count.moe:,.0f}" in figure.text
        assert "reliable" in figure.text
        assert "Relevant need only" in card.text
        assert "agency decides eligibility" in card.text
        for fact in match.count.inputs:
            for field in (fact.source, fact.table_id, fact.vintage, fact.geography, fact.method):
                assert field in figure.text
    assert len(programs.find_all("li", class_="program")) == len(
        load_catalog(ROOT / "data/programs.yaml")
    )


def test_missing_facts_keep_catalog_referrals_and_unavailable_permalink(
    policy: Path, complete_store: Path
) -> None:
    with sqlite3.connect(complete_store) as db:
        db.execute("DELETE FROM facts")
    client = TestClient(app)
    response = client.get("/brief/house/22")
    assert response.status_code == 200
    programs = parse(response.text).one("section", class_="programs")
    assert not programs.find_all("article", class_="case")
    for program in load_catalog(ROOT / "data/programs.yaml"):
        item = programs.one("li", data_program=program.name)
        links = {a.attrs["href"] for a in item.find_all("a")}
        assert str(program.official_url) in links and program.referral_url in links
        assert "agency decides eligibility" in item.text
    response = client.get("/match/house/22/public-pre-k/children_under_5")
    assert response.status_code == 200
    card = parse(response.text).one("article", class_="case")
    for text in ("Not available", "Margin of error unavailable", "insufficient", "B01001_003E"):
        assert text in card.text


def test_missing_county_contacts_preserve_evidence_and_guidance_before_disclosure(
    policy: Path, complete_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_contacts() -> list[ProgramContact]:
        return []

    monkeypatch.setattr(program_cards, "load_contacts", no_contacts)
    cards = program_cards.load_cards(DISTRICT)
    assert cards
    response = TestClient(app).get("/brief/house/22")
    assert response.status_code == 200
    programs = parse(response.text).one("section", class_="programs")
    for program in cards:
        card = program.match
        wrapper = programs.one(data_program_card=f"{card.program_id}:{card.population_id}")
        disclosure = wrapper.one("details", class_="source")
        assert disclosure.one("article", class_="case")
        assert program.guidance in wrapper.text
        assert program.wording.missing_contacts in wrapper.text
        for county in program.counties:
            assert county.name in wrapper.text
        # Supplementary steps remain usable without expanding the evidence.
        before = wrapper.children[: wrapper.children.index(disclosure)]
        text = " ".join(node.text for node in before)
        assert program.guidance in text and program.wording.missing_contacts in text
        assert all(step in text for step in card.next_steps)
        links = {a.attrs["href"] for node in before for a in node.find_all("a")}
        assert str(card.official_url) in links and str(card.referral_url) in links
    email = templates.get_template("partials/program-cards.html").render(
        program_cards=cards, email=True
    )
    assert "<details" not in email and "screen-only" not in email
    assert complete_articles(email) == complete_articles(
        response.text.split('<section class="programs">', 1)[1].split("</section>", 1)[0]
    )


@pytest.mark.parametrize("flag", ['program_cards = "off"', ""])
def test_disabled_or_omitted_flag_keeps_catalog_without_loading_matches(
    policy: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    policy.write_text('outreach = "on"\n' + flag)

    def forbidden(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        pytest.fail("disabled program cards must not load matches")

    monkeypatch.setattr(DistrictMatches, "get_matches", forbidden)
    for suffix in ("", "?preview=1"):
        response = TestClient(app).get("/brief/house/22" + suffix)
        assert response.status_code == 200
        programs = parse(response.text).one("section", class_="programs")
        assert len(programs.find_all("li", class_="program")) == 4
        assert not programs.find_all("article")
        assert "data-program-card" not in response.text


@pytest.mark.parametrize("width", [390, 768, 1440])
def test_disclosed_cards_pass_axe_and_preserve_print_policy(
    policy: Path, complete_store: Path, monkeypatch: pytest.MonkeyPatch, page: Page, width: int
) -> None:
    ranked = DistrictMatches(DISTRICT).get_matches()

    def detached(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        return ranked

    monkeypatch.setattr(DistrictMatches, "get_matches", detached)
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    response = TestClient(app).get("/brief/house/22")
    assert response.status_code == 200
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(response.text)
    for stylesheet in ("tokens.css", "site.css"):
        page.add_style_tag(path=str(ROOT / "static" / stylesheet))
    assert axe_problems(page) == []
    wrappers = page.locator(".programs [data-program-card]")
    assert wrappers.count() > 0
    assert all(w.is_visible() for w in wrappers.all())
    assert page.locator(".programs article.case").count() > 0
    assert not page.locator(".programs article.case").first.is_visible()
    for summary in page.locator(".programs details.source > summary").all():
        summary.focus()
        page.keyboard.press("Enter")
    assert all(c.is_visible() for c in page.locator(".programs article.case").all())
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert all(not w.is_visible() for w in wrappers.all())
    assert all(p.is_visible() for p in page.locator(".programs .program").all())
    assert pdf_pages(page) == 1
