"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

import importlib

from fastapi.testclient import TestClient
from playwright.sync_api import Route, sync_playwright

from app import cases, snap
from app.brief import discover
from app.main import app
from app.main import app as asgi_app
from etl.boundaries import DISTRICT_COUNTS, DistrictId
from tests.regressions.test_journey_opening_case import CASE_COPY, card, flat, record
from tests.regressions.test_wo122_browser_checks import base_url, browser
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo136_surfaces import outreach
from tests.regressions.test_wo143_integration import config, live_config, shipped_facts

__all__ = [
    "CASE_COPY",
    "base_url",
    "browser",
    "card",
    "config",
    "flat",
    "live_config",
    "outreach",
    "page",
    "record",
    "shipped_facts",
]


# Replaces test_journey_opening_case.py::test_card_says_who_why_and_what_next (wording only, #187).
def test_card_says_who_why_and_what_next() -> None:
    found = card(TestClient(asgi_app), "/brief/senate/5")
    record = cases.case("snap_no_receipt")
    result = snap.load_result(DistrictId(chamber="senate", district=5))
    assert found.one("h2").text == "Households in poverty that say they got no SNAP · SNAP"
    text = flat(found)
    assert record.claim in text
    assert "survey-reported receipt over the past 12 months" in record.claim
    assert "an outreach signal" in record.claim
    assert "not current enrollment" in record.claim
    for words in (*record.known.values(), *record.unknown.values()):
        assert words in text
    assert CASE_COPY["known_label"] in text and CASE_COPY["unknown_label"] in text
    assert CASE_COPY["gaps"][record.failure.gap] in text
    assert record.failure.note in text
    assert CASE_COPY["actions"][record.action.kind] in text
    assert result.referral_note in text
    assert "may help" in text and "DHS decides eligibility" in text
    assert record.program.rule_checked.isoformat() in text


# Replaces test_wo136_surfaces.py::test_all_districts_render_canonical_cited_comparisons (wording only, #187).
def test_all_districts_render_canonical_cited_comparisons() -> None:
    assert "outreach" in [section.name for section in discover()]
    module = importlib.import_module("app.sections.40_outreach")
    assert module.PRINT is True
    for chamber, count in DISTRICT_COUNTS.items():
        for number in range(1, count + 1):
            result = snap.load_result(
                DistrictId.model_validate({"chamber": chamber, "district": number})
            )
            section = outreach(chamber, number)
            assert section.one("h2").text == "Households in poverty that say they got no SNAP"
            table = section.one("table")
            assert table.one("caption").text
            assert all(th.attrs.get("scope") == "col" for th in table.one("thead").find_all("th"))
            rows = table.one("tbody").find_all("tr")
            for row, reading in zip(
                rows, [result.district, *result.counties, result.state], strict=True
            ):
                assert row.one("th", scope="row").text == reading.geography_name
                for text in (
                    reading.value_text,
                    reading.moe_text,
                    reading.reliability_word,
                    reading.units,
                ):
                    assert text in row.text
                assert reading.fact is not None
                for field in ("source", "table_id", "vintage", "geography", "method", "endpoint"):
                    # Word-break elements split parser chunks without adding visible spaces.
                    citation = " ".join("".join(row.one("dl").parts).split())
                    assert str(getattr(reading.fact, field)) in citation
            for note in (
                result.undercount_note,
                result.referral_note,
            ):
                assert note in section.text
            assert "ACS uses national Census poverty thresholds" in section.text
            assert "ACS asks if a household got SNAP in the past 12 months" in section.text
            assert "not current enrollment or eligibility" in section.text
            assert "income under the poverty threshold" in section.text
            assert "They are lower than the Hawaiʻi HHS poverty guidelines" in section.text
            assert "does not decide who is eligible" in section.text
            assert "eligible for" not in section.text
            hrefs = [a.attrs.get("href") for a in section.find_all("a")]
            assert result.official_url in hrefs
            assert result.referral_url in hrefs


# Replaces test_wo303_snap_region_name.py::test_snap_region_exact_name_preserves_case_evidence (wording only, #187).
def test_snap_region_exact_name_preserves_case_evidence() -> None:
    client = TestClient(app)
    result = snap.load_result(DistrictId(chamber="house", district=22))
    fact = result.district.fact
    assert fact is not None

    def fulfil(route: Route) -> None:
        response = client.get(route.request.url.replace("http://kyd", ""))
        route.fulfill(
            body=response.content,
            status=response.status_code,
            content_type=response.headers["content-type"],
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("http://kyd/**", fulfil)
        page.goto("http://kyd/brief/house/22")
        case = page.get_by_role("region", name="SNAP", exact=True)
        assert case.count() == 1
        assert case.is_visible()
        assert case.get_by_role("heading", level=2).inner_text() == (
            "Households in poverty that say they got no SNAP · SNAP"
        )
        text = case.inner_text()
        for expected in (
            result.district.value_text,
            result.district.units,
            result.district.moe_text,
            result.district.reliability_word,
            fact.source,
            fact.table_id,
            fact.vintage,
            fact.geography,
            fact.method,
            result.undercount_note,
            "not current enrollment",
            "Hawaiʻi rules cover who counts as a household, which costs can be deducted, "
            "and more than income. The survey does not cover all these rules.",
            "DHS decides eligibility",
        ):
            assert expected in text
        next_step = case.get_by_role("link", name="official next step", exact=True)
        assert next_step.count() == 1
        assert next_step.is_visible()
        assert next_step.get_attribute("href") == "https://humanservices.hawaii.gov/bessd/snap/"
        browser.close()
