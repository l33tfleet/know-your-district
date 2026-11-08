"""#373: recipient-free outreach drafts retain detached, cited population evidence."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.main import app, templates
from app.program_cards import load_cards
from app.tools.matches import DistrictMatches, ProgramMatch
from etl.boundaries import Chamber, DistrictId
from etl.programs import FORBIDDEN
from tests.regressions.test_wo122_browser_checks import (
    axe_problems,
    base_url,
    browser,
    open_page,
    page,
)
from tests.regressions.test_wo143_integration import pdf_pages
from tests.regressions.test_wo149_matches import matching_store
from tests.regressions.test_wo150_cards import policy, render
from tests.regressions.test_wo150_prek import complete_store

__all__ = ["base_url", "browser", "complete_store", "matching_store", "page", "policy"]
ROOT = Path(__file__).resolve().parents[2]
DISTRICT = DistrictId(chamber="house", district=22)
LABEL = "Ask the agency about outreach here"


class MailLinks(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__()
        self.urls: list[str] = []
        self.feed(markup)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag == "a" and href and href.startswith("mailto:"):
            self.urls.append(href)


def decode(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    assert parsed.scheme == "mailto"
    assert parsed.path == parsed.netloc == parsed.fragment == ""
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    assert [key for key, _ in pairs] == ["subject", "body"]
    assert "%20" in url and "+" not in url and "\n" not in url
    subject, body = [value for _, value in pairs]
    assert not any(phrase in " ".join((subject + body).casefold().split()) for phrase in FORBIDDEN)
    return subject, body


@pytest.mark.parametrize("chamber,number", [("house", 22), ("senate", 5)])
def test_rendered_brief_drafts_preserve_tool_evidence(
    policy: Path, complete_store: Path, chamber: Chamber, number: int
) -> None:
    district = DistrictId(chamber=chamber, district=number)
    strong = [m for m in DistrictMatches(district).get_matches() if m.result.band == "strong"]
    assert strong
    with TestClient(app, base_url="https://untrusted.example") as client:
        response = client.get(f"/brief/{chamber}/{number}?resident=PRIVATE&v=b")
        repeated = client.get(f"/brief/{chamber}/{number}")
    assert response.status_code == 200
    urls = MailLinks(response.text).urls
    assert len(urls) == len(strong)
    assert response.text.count(LABEL) == len(strong)
    for url, match in zip(urls, strong, strict=True):
        subject, body = decode(url)
        assert match.program.name in subject and str(number) in subject
        for text in (
            f"https://district.hawaiitechmentors.org/brief/{chamber}/{number}",
            match.population.label,
            match.population.definition,
            match.population.universe,
            match.result.reason,
            match.mapping.relevance,
            match.program.guidance,
            str(match.program.official_url),
            str(match.program.referral_url),
            "Relevant need only",
            "agency decides eligibility",
            *match.population.exclusions,
            *match.mapping.observed_conditions,
            *match.mapping.unobserved_conditions,
        ):
            assert text in body
        for figure in (match.count, *match.result.figures):
            assert str(figure.value) in body
            assert str(figure.moe) in body
            assert figure.method in body
            for fact in figure.inputs:
                for text in (
                    fact.source,
                    fact.table_id,
                    fact.variable,
                    fact.vintage,
                    fact.geography,
                    fact.method,
                    str(fact.endpoint),
                ):
                    assert text in body
        assert match.population.unit in body and "90% margin of error" in body
        assert "reliable" in body
        assert "PRIVATE" not in body and "untrusted.example" not in body and "?v=" not in body
    assert urls == MailLinks(repeated.text).urls


@pytest.mark.parametrize("missing_value", [False, True])
def test_encoding_and_unavailable_uncertainty(
    policy: Path, complete_store: Path, monkeypatch: pytest.MonkeyPatch, missing_value: bool
) -> None:
    original = DistrictMatches(DISTRICT).get_matches()[0]
    special = "Hawaiʻi & Kauaʻi + Oʻahu\nOutreach context"
    altered = original.model_copy(
        update={
            "program": original.program.model_copy(update={"name": special}),
            "count": original.count.model_copy(
                update={
                    "value": None if missing_value else original.count.value,
                    "moe": None,
                    "cv": None,
                    "reliability": "caution",
                }
            ),
        }
    )

    def detached(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        return (altered,)

    monkeypatch.setattr(DistrictMatches, "get_matches", detached)
    urls = MailLinks(render()).urls
    assert len(urls) == 1
    subject, body = decode(urls[0])
    assert special in subject and special in body
    assert "%26" in urls[0] and "%2B" in urls[0] and "%0A" in urls[0]
    assert "Margin of error unavailable" in body and "use with caution" in body
    if missing_value:
        assert "Not available" in body
    assert "None" not in body


@pytest.mark.parametrize(
    "status,preview,visible",
    [
        ("off", False, False),
        ("off", True, False),
        ("preview", False, False),
        ("preview", True, True),
        ("on", False, True),
    ],
)
def test_email_action_gating_and_standalone_excerpt(
    policy: Path, complete_store: Path, status: str, preview: bool, visible: bool
) -> None:
    policy.write_text(f'program_cards = "{status}"\n')
    assert bool(MailLinks(render(preview=preview)).urls) == visible
    if visible:
        assert not MailLinks(render(preview=preview, email=True)).urls
        assert "screen-only" not in render(preview=preview, email=True)
        cards = load_cards(DISTRICT)
        excerpt = templates.get_template("partials/program-outreach-email.html").render(
            program=cards[0]
        )
        assert len(MailLinks(excerpt).urls) == 1 and LABEL in excerpt


def test_email_action_axe_and_print(
    page: Page,
    base_url: str,
    policy: Path,
    complete_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranked = DistrictMatches(DISTRICT).get_matches()

    def detached(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        return ranked

    monkeypatch.setattr(DistrictMatches, "get_matches", detached)
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    open_page(page, base_url + "/brief/house/22", 1440)
    action = page.get_by_role("link", name=LABEL).first
    assert action.is_visible()
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert not action.is_visible()
    assert page.locator(".program-list .program").count() == 4
    assert page.locator('.figure [data-field="table_id"]').first.is_visible()
    assert pdf_pages(page) == 1
