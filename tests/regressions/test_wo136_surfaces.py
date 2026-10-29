"""WO161: canonical outreach estimates remain cited, printable and switchable."""

import importlib
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app import snap
from app.brief import discover
from app.main import app
from etl.boundaries import DISTRICT_COUNTS, DistrictId
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import axe_problems

ROOT = Path(__file__).resolve().parents[2]


def outreach(chamber: str = "house", number: int = 22) -> Node:
    response = TestClient(app).get(f"/brief/{chamber}/{number}")
    assert response.status_code == 200
    return parse(response.text).one("section", class_="outreach")


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
            assert section.one("h2").text == "Households in poverty reporting no SNAP receipt"
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
            assert "survey-reported receipt over the past 12 months" in section.text
            assert "not current enrollment or eligibility" in section.text
            assert "income under the poverty threshold" in section.text
            assert "Hawaiʻi HHS poverty guidelines (which exceed Census thresholds)" in section.text
            assert "does not determine eligibility" in section.text
            assert "eligible for" not in section.text
            hrefs = [a.attrs.get("href") for a in section.find_all("a")]
            assert result.official_url in hrefs
            assert result.referral_url in hrefs


@pytest.mark.parametrize("missing", ["database", "row", "estimate", "moe", "zero"])
def test_outreach_explains_missing_inputs_and_preserves_caution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    database = tmp_path / "facts.db"
    if missing != "database":
        shutil.copyfile(snap.SNAP_DB, database)
        with sqlite3.connect(database) as db:
            geography = "house:15:022:2022"
            if missing == "row":
                db.execute("DELETE FROM facts WHERE geography = ?", [geography])
            else:
                column = "moe" if missing == "moe" else "value"
                value = 0 if missing == "zero" else None
                flag = "unavailable" if missing == "estimate" else "caution"
                db.execute(
                    f"UPDATE facts SET {column} = ?, cv = NULL, reliability = ? WHERE geography = ?",
                    [value, flag, geography],
                )
    monkeypatch.setattr(snap, "SNAP_DB", database)
    row = outreach().one("tbody").find_all("tr")[0]
    if missing in {"database", "row"}:
        assert "No published figure in the fact table yet." in row.text
    elif missing == "estimate":
        assert "not available" in row.text
        fact = snap.load_result(DistrictId(chamber="house", district=22)).district.fact
        assert fact is not None
        assert fact.method in " ".join("".join(row.one("dl").parts).split())
    elif missing == "moe":
        assert "no margin of error published" in row.text
        assert "use with caution" in row.text
    else:
        assert "0 households;" in row.text
        assert "use with caution" in row.text


def test_off_hides_outreach_and_skips_result_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import features

    config = tmp_path / "features.toml"
    config.write_text("outreach = false\n")
    monkeypatch.setattr(features, "FEATURES_PATH", config)

    def forbidden(district: DistrictId) -> snap.SnapResult:
        pytest.fail("disabled outreach must not load facts")

    monkeypatch.setattr(snap, "load_result", forbidden)
    response = TestClient(app).get("/brief/house/22")
    assert response.status_code == 200
    assert not parse(response.text).find_all("section", class_="outreach")
    assert "B22003" not in response.text
    assert "SNAP receipt" not in response.text


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("variant", ["", "a", "b"])
@pytest.mark.parametrize("width", [390, 1440])
def test_screen_and_print_show_same_outreach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool, variant: str, width: int
) -> None:
    from app import features

    config = tmp_path / "features.toml"
    config.write_text(f"outreach = {str(enabled).lower()}\n")
    monkeypatch.setattr(features, "FEATURES_PATH", config)
    client = TestClient(app)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.route(
            "http://kyd/**",
            lambda route: route.fulfill(
                body=client.get(route.request.url.replace("http://kyd", "")).content,
                content_type="text/css" if route.request.url.endswith(".css") else "text/html",
            ),
        )
        page.goto(
            f"http://kyd/brief/house/22?v={variant}" if variant else "http://kyd/brief/house/22"
        )
        assert axe_problems(page) == []
        section = page.locator(".outreach")
        screen = section.inner_text() if enabled else ""
        if enabled:
            assert section.is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        else:
            assert section.count() == 0
        page.emulate_media(media="print")
        if enabled:
            assert section.is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert section.inner_text() == screen
            for cell in section.locator("th, td").all():
                assert cell.is_visible()
        else:
            assert section.count() == 0
        browser.close()


@pytest.mark.parametrize(
    "config,error",
    [
        ("outreach = 'false'", "bool_type"),
        ("outreach = true\nunknown = true", "extra_forbidden"),
        ("", "missing"),
    ],
)
def test_feature_configuration_rejects_invalid_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str, error: str
) -> None:
    from pydantic import ValidationError

    from app import features

    path = tmp_path / "features.toml"
    path.write_text(config)
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    with pytest.raises(ValidationError, match=error):
        features.load_features()
