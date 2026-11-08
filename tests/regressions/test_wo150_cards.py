"""#372: separately flagged strong program cards preserve evidence and county scope."""

import html
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from jinja2 import Environment
from playwright.sync_api import Page

from app import features
from app.copy import section_copy
from app.counties import load_mapping
from app.main import templates
from app.page_state import PageState
from app.program_contacts import ProgramContact
from app.tools.matches import DistrictMatches, ProgramMatch
from etl.boundaries import DistrictId
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
from tests.regressions.test_wo150_prek import complete_store

__all__ = ["base_url", "browser", "complete_store", "matching_store", "page"]
ROOT = Path(__file__).resolve().parents[2]
DISTRICT = DistrictId(chamber="house", district=22)

# Characterize the pre-card catalog markup, including whitespace.
LEGACY_TEMPLATE = """<section class="programs">
  <h2>{{ copy.heading }}</h2>
  <ul class="program-list">
    {% for p in section.programs %}
    <li class="program" data-program="{{ p.name }}">
      <h3 class="program-name">{{ p.name }}</h3>
      <p class="program-agency">{{ p.agency }}</p>
      <p class="program-purpose">{{ p.purpose }}</p>
      <p class="program-official"><a href="{{ p.official_url }}">{{ copy.official_link }}</a></p>
      <p class="program-guidance">{{ p.guidance }}
        <a href="{{ p.referral_url }}">{{ copy.referral_link }}</a></p>
    </li>
    {% endfor %}
  </ul>
</section>
"""


@pytest.fixture
def policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "features.toml"
    path.write_text('outreach = "on"\nprogram_cards = "on"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    return path


@pytest.mark.parametrize("status", ["off", "on", "preview", None, "bogus"])
def test_fresh_startup(status: str | None, tmp_path: Path) -> None:
    config = tmp_path / "flags.toml"
    config.write_text("" if status is None else f'program_cards = "{status}"\n')
    script = """
import sys
from pathlib import Path
from app import features
features.FEATURES_PATH = Path(sys.argv[1])
from app.main import validate_startup
assert "app.sections.30_programs" not in sys.modules
validate_startup()
from app.page_state import PageState
from etl.boundaries import DistrictId
state = PageState(district=DistrictId(chamber="house", district=22))
assert features.enabled("program_cards", state) == (sys.argv[2] == "on")
assert features.enabled("program_cards", state.model_copy(update={"preview": True})) == (sys.argv[2] in ("on", "preview"))
assert "app.sections.30_programs" not in sys.modules
features.FEATURES_PATH.write_text('unknown_cards = "on"')
validate_startup()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(config), status or "omitted"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    if status == "bogus":
        assert "valid statuses: on, off, preview" in result.stderr
    else:
        assert "Unknown feature 'unknown_cards'" in result.stderr, result.stderr


def render(*, preview: bool = False, email: bool = False) -> str:
    section = import_module("app.sections.30_programs")
    context = section.context(PageState(district=DISTRICT, preview=preview))
    if email:
        return templates.get_template("partials/program-cards.html").render(
            program_cards=context["program_cards"], email=True
        )
    return templates.get_template("sections/30-programs.html").render(
        section=context, copy=section_copy("programs")
    )


def test_disabled_is_identical_catalog_and_never_reads_matches_or_contacts(
    policy: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import program_cards

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("disabled cards must not load matching or contact data")

    monkeypatch.setattr(DistrictMatches, "get_matches", forbidden)
    monkeypatch.setattr(program_cards, "load_contacts", forbidden)
    section = import_module("app.sections.30_programs")
    baseline = templates.get_template("sections/30-programs.html").render(
        section={"programs": section.programs()}, copy=section_copy("programs")
    )
    for config in ('program_cards = "off"', 'program_cards = "preview"', ""):
        policy.write_text(config)
        assert baseline == Environment(autoescape=True).from_string(LEGACY_TEMPLATE).render(
            section={"programs": section.programs()}, copy=section_copy("programs")
        )
        assert render() == baseline
        if config != 'program_cards = "preview"':
            assert render(preview=True) == baseline
    assert section.context(PageState(district=DISTRICT)) == {"programs": section.programs()}


def test_strong_ranked_cards_preserve_claim_evidence_and_missing_contact_fallback(
    policy: Path,
    complete_store: Path,
) -> None:
    matches = DistrictMatches(DISTRICT).get_matches()
    strong = [m for m in matches if m.result.band == "strong"]
    assert strong[0].program.id == "public-pre-k"
    rendered = html.unescape(render())
    positions = [
        rendered.index(f'data-program-card="{m.program.id}:{m.population.id}"') for m in strong
    ]
    assert positions == sorted(positions)
    for match in matches:
        marker = f'data-program-card="{match.program.id}:{match.population.id}"'
        assert (marker in rendered) == (match.result.band == "strong")
    card = rendered.split('data-program-card="public-pre-k:children_under_5"')[1].split(
        "</article>"
    )[0]
    for text in (
        strong[0].result.reason,
        strong[0].mapping.relevance,
        strong[0].program.guidance,
        strong[0].population.label,
        "Relevant need only",
        "90% margin of error",
        "reliable",
        "agency decides eligibility",
        "Official program information",
        "Aloha United Way 211",
        "County contacts not documented",
        "Honolulu",
    ):
        assert text in card
    for fact in strong[0].count.inputs:
        for text in (fact.source, fact.table_id, fact.vintage, fact.geography, fact.method):
            assert text in card
    assert not any(phrase in " ".join(rendered.casefold().split()) for phrase in FORBIDDEN)
    email = html.unescape(render(email=True))
    assert strong[0].result.reason in email
    assert "screen-only" not in email and "<details" not in email


def test_preview_and_tool_order_are_respected(
    policy: Path,
    complete_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranked = DistrictMatches(DISTRICT).get_matches()
    strong = tuple(
        m.model_copy(update={"result": m.result.model_copy(update={"band": "strong"})})
        for m in ranked
    )
    assert len(strong) > 1

    # Consumer preserves the tool order even when pre-K is not the leading result.
    def reordered(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        return tuple(reversed(strong))

    monkeypatch.setattr(DistrictMatches, "get_matches", reordered)
    policy.write_text('program_cards = "preview"')
    assert "data-program-card=" not in render()
    shown = render(preview=True)
    positions = [
        shown.index(f'data-program-card="{m.program.id}:{m.population.id}"')
        for m in reversed(strong)
    ]
    assert positions == sorted(positions)


def test_every_mapped_county_offices_and_partners_without_unmapped_contacts(
    policy: Path,
    complete_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import program_cards

    mapping = load_mapping()
    sample = mapping[DISTRICT.fact_key][0]
    mapping[DISTRICT.fact_key] = [
        sample.model_copy(update={"county": f"county:15:{code}", "area_share": 0.5})
        for code in ("001", "009")
    ]
    monkeypatch.setattr(program_cards, "load_mapping", lambda: mapping)
    snap = next(m for m in DistrictMatches(DISTRICT).get_matches() if m.program.id == "snap")
    snap = snap.model_copy(update={"result": snap.result.model_copy(update={"band": "strong"})})

    def snap_only(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        return (snap,)

    monkeypatch.setattr(DistrictMatches, "get_matches", snap_only)
    shown = html.unescape(render())
    article = shown.split('data-program-card="snap:below_poverty_no_snap"')[1].split("</article>")[
        0
    ]
    assert "Hawaiʻi County" in article and "Maui County" in article
    assert "Honolulu" not in article and "Kauaʻi" not in article
    assert article.count("Agency office") == 2 and article.count("Partner") == 2
    assert "2026-10-28" in article and "capacity" in article

    def no_contacts() -> list[ProgramContact]:
        return []

    monkeypatch.setattr(program_cards, "load_contacts", no_contacts)
    missing = render()
    assert "County contacts not documented" in missing
    assert str(snap.program.official_url) in missing and "https://www.auw211.org/" in missing


@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
def test_cards_axe_and_one_letter_page_with_printable_citations(
    page: Page,
    base_url: str,
    policy: Path,
    complete_store: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    # Keep the full shipped brief; inject only the matching tool's detached results.
    ranked = DistrictMatches(DISTRICT).get_matches()

    def detached(self: DistrictMatches) -> tuple[ProgramMatch, ...]:
        return ranked

    monkeypatch.setattr(DistrictMatches, "get_matches", detached)
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    open_page(page, base_url + "/brief/house/22" + variant, 1440)
    assert page.locator('[data-program-card="public-pre-k:children_under_5"]').is_visible()
    assert axe_problems(page) == []
    page.locator("[data-program-card] details summary").first.click()
    assert page.locator("[data-program-card] details").first.get_attribute("open") is not None
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert not page.locator("[data-program-card]").first.is_visible()
    assert page.locator(".programs .program").count() == 4
    assert page.locator(".programs .program").first.is_visible()
    for field in ("source", "table_id", "vintage", "geography", "method"):
        assert page.locator(f'.figure [data-field="{field}"]').first.is_visible()
    assert pdf_pages(page) == 1
