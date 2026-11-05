"""WO201: offline coastline states, responsive ink, accessible names and Letter printing."""

import json
import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page

import app.boundary_store as boundaries
from tests.regressions.test_wo122_browser_checks import (
    ROOT,
    axe_problems,
    base_url,
    browser,
    open_page,
    page,
    page_text,
    spelling_problems,
)
from tests.regressions.test_wo143_integration import pdf_pages

__all__ = ["base_url", "browser", "page"]
NAMES = ["Maui", "Kahoʻolawe", "Lānaʻi", "Molokaʻi"]
CREDIT = 'Synthetic Hawaii coastline source <survey> & "credit"'


@pytest.fixture
def coastlines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Complete synthetic geometry, never a substitute for production coastlines."""
    geo = Path(shutil.copytree(boundaries.GEO_DIR, tmp_path / "geo"))
    monkeypatch.setattr(boundaries, "GEO_DIR", geo)
    return geo


def add_coastlines(geo: Path) -> None:
    path = geo / "islands/islands.json"
    document = json.loads(path.read_text())
    source = json.loads(
        (ROOT / "tests/regressions/fixtures/wo145_islands/coastline.source.json").read_text()
    )
    source["credit"] = CREDIT
    features: list[dict[str, object]] = []
    # Distinct synthetic rectangles at each island, including every House 13 island.
    for island, (x, y) in zip(
        document["islands"][1:5],
        [(-156.5, 20.8), (-156.6, 20.5), (-157.0, 20.8), (-157.0, 21.1)],
        strict=True,
    ):
        island["coastline"] = {"status": "available", "source": source}
        features.append(
            {
                "type": "Feature",
                "properties": {"island": island["id"]},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [x, y],
                                [x + 0.1, y],
                                [x + 0.1, y + 0.1],
                                [x, y + 0.1],
                                [x, y],
                            ]
                        ]
                    ],
                },
            }
        )
    path.write_text(json.dumps(document))
    (geo / "islands/coastlines.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": features,
            }
        )
    )
    with (geo / "islands/credit.txt").open("a") as file:
        file.write(CREDIT + "\n")
    assert len(boundaries.load_boundaries(geo).district("house:15:013:2022").islands) == 4


def assert_ink(page: Page, width: int) -> None:
    svg = page.locator(".headline-map svg")
    assert svg.is_visible()
    box = svg.bounding_box()
    assert box is not None and box["width"] > 0 and box["height"] > 0
    assert box["x"] >= 0 and box["x"] + box["width"] <= width
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for path in svg.locator("path").all():
        assert path.evaluate(
            "e => {const b=e.getBBox(), s=getComputedStyle(e);"
            "return b.width > 0 && b.height > 0 && s.fill !== 'none'"
            " && s.fill !== 'rgba(0, 0, 0, 0)' && +s.opacity > 0"
            " && s.visibility === 'visible' && s.display !== 'none'}"
        )
    assert page.locator(".boundary-source").is_visible()


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("width", [390, 1440])
def test_multi_island_coastline_states(
    page: Page, base_url: str, coastlines: Path, available: bool, width: int
) -> None:
    if available:
        add_coastlines(coastlines)
    open_page(page, base_url + "/brief/house/13", width)
    svg = page.locator(".headline-map svg")
    assert svg.count() == 1
    assert svg.get_attribute("aria-label") == "Hawaiʻi State House District 13; " + "; ".join(NAMES)
    assert page.get_by_role("img", name=svg.get_attribute("aria-label"), exact=True).count() == 1
    paths = svg.locator("path")
    assert paths.count() == (5 if available else 1)
    if available:
        assert [p.get_attribute("aria-label") for p in paths.all()[:-1]] == NAMES
        for path in paths.all()[:-1]:
            assert float(path.evaluate("e => getComputedStyle(e).opacity")) < 0.5
        assert CREDIT.replace("Hawaii", "Hawaiʻi") in page.locator(".boundary-source").inner_text()
        assert page.locator(".boundary-source survey").count() == 0
    else:
        assert CREDIT not in page.locator(".boundary-source").inner_text()
    assert_ink(page, width)
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert_ink(page, width)


@pytest.mark.parametrize("chamber,number", [("house", 22), ("senate", 8)])
@pytest.mark.parametrize("width", [390, 1440])
def test_production_chambers_mobile_and_print(
    page: Page, base_url: str, chamber: str, number: int, width: int
) -> None:
    open_page(page, f"{base_url}/brief/{chamber}/{number}", width)
    entry = boundaries.load_boundaries().district(f"{chamber}:15:{number:03}:2022")
    svg = page.locator(".headline-map svg")
    assert svg.count() == 1
    assert svg.locator("path").count() == 1 + sum(i.geometry is not None for i in entry.islands)
    label = svg.get_attribute("aria-label") or ""
    assert all(i.name in label for i in entry.islands)
    assert (
        entry.attribution.credit.replace("Hawaii", "Hawaiʻi")
        in page.locator(".boundary-source").inner_text()
    )
    assert_ink(page, width)
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert_ink(page, width)


@pytest.mark.parametrize("path", ["/brief/house/22", "/brief/senate/5"])
@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
def test_complete_brief_retains_one_letter_page(
    page: Page, base_url: str, monkeypatch: pytest.MonkeyPatch, variant: str, path: str
) -> None:
    monkeypatch.setenv("KYD_FACTS_DB", str(ROOT / "data/facts.db"))
    open_page(page, base_url + path + variant, 1440)
    assert page.locator(".figure .reading[data-geography^='county:']").count() == 3
    page.add_style_tag(content=".brief, .site-footer { letter-spacing: 0.04em; }")
    assert pdf_pages(page) == 1
    page.emulate_media(media="print")
    assert_ink(page, 1440)
    evidence = Path("/tmp/wo201-print")
    evidence.mkdir(exist_ok=True)
    suffix = re.sub(r"\W", "", variant) or "default"
    page.pdf(
        path=str(evidence / f"{path.rsplit('/', 2)[1]}-{suffix}.pdf"), prefer_css_page_size=True
    )


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_boundary_attribution_uses_hawaiian_spelling(
    page: Page, base_url: str, chamber: str
) -> None:
    open_page(page, f"{base_url}/brief/{chamber}/22", 390)
    assert spelling_problems(page_text(page)) == []
    assert "Hawaiʻi Statewide GIS Program" in page.locator(".boundary-source").inner_text()


@pytest.mark.parametrize("chamber,number", [("house", 22), ("senate", 8), ("house", 13)])
@pytest.mark.parametrize("width", [390, 1440])
def test_story_glance_map_has_visible_table_twin(
    page: Page, base_url: str, chamber: str, number: int, width: int
) -> None:
    open_page(page, f"{base_url}/brief/{chamber}/{number}", width)
    region = page.get_by_role("region", name="District map", exact=True)
    assert region.count() == 1
    table = region.get_by_role("table", name="District map as a table", exact=True)
    assert table.is_visible()
    assert region.get_by_role("img").is_visible()
    assert region.get_by_role("heading", level=1).is_visible()
    entry = boundaries.load_boundaries().district(f"{chamber}:15:{number:03}:2022")
    assert table.get_by_role("cell", name=page.locator("h1").inner_text(), exact=True).is_visible()
    assert table.get_by_role("cell", name="; ".join(i.name for i in entry.islands)).is_visible()
    assert axe_problems(page) == []
    assert_ink(page, width)
    page.emulate_media(media="print")
    assert table.is_visible()
    assert_ink(page, width)
