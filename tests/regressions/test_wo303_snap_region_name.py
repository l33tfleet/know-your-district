"""WO303: the SNAP case has the exact accessible name used by story step 4."""

from fastapi.testclient import TestClient
from playwright.sync_api import Route, sync_playwright

from app import snap
from app.main import app
from etl.boundaries import DistrictId


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
            "Households in poverty reporting no SNAP receipt · SNAP"
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
            "Hawaiʻi household, deduction and nonfinancial rules are not in the survey.",
            "DHS decides eligibility",
        ):
            assert expected in text
        next_step = case.get_by_role("link", name="official next step", exact=True)
        assert next_step.count() == 1
        assert next_step.is_visible()
        assert next_step.get_attribute("href") == "https://humanservices.hawaii.gov/bessd/snap/"
        browser.close()
