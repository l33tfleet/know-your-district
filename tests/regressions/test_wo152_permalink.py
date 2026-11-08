"""#221: canonical, gated match permalinks retain evidence on screen and print."""

import sqlite3
import subprocess
import sys
from datetime import date
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.main import app
from app.tools.matches import DistrictMatches
from etl.programs import Program, load_catalog
from etl.programs.mappings import load_mappings
from tests.regressions.test_wo122_browser_checks import axe_problems, browser, page
from tests.regressions.test_wo149_matches import matching_store

__all__ = ["browser", "matching_store", "page"]
ROOT = Path(__file__).resolve().parents[2]
PATH = "/match/house/22/snap/below_poverty_no_snap"


@pytest.mark.parametrize("module", ["app.web.matches", "app.main"])
def test_permalink_registration_preserves_startup_case_loading(module: str) -> None:
    """Registering the permalink must leave case validation to application startup."""
    program = (
        f"import {module}\n"
        "import sys\n"
        "assert 'app.cases' not in sys.modules\n"
        "from app.main import validate_startup\n"
        "validate_startup()\n"
        "assert 'app.cases' in sys.modules\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_permalink_uses_shared_cited_card(chamber: str, matching_store: Path) -> None:
    response = TestClient(app).get(PATH.replace("house", chamber) + "?preview=1")
    assert response.status_code == 200
    assert f'data-match="{chamber}:15:022:2022:below_poverty_no_snap:snap"' in response.text
    for text in (
        "Synthetic Census fixture",
        "B22003",
        "2020–2024",
        "90% margin of error",
        "published estimate and 90% margin of error",
        "reliable",
        "Relevant need only",
        "agency decides eligibility",
        "Aloha United Way 211",
        "What we know",
    ):
        assert text in response.text


@pytest.mark.parametrize(
    "suffix",
    [
        "/house/22/unknown/below_poverty_no_snap",
        "/house/22/snap/unknown",
        "/house/22/SNAP/below_poverty_no_snap",
        "/house/22/supplemental-nutrition-assistance-program/below_poverty_no_snap",
        "/house/22/snap/disability",  # Both IDs exist, but this match does not.
        "/house/0/snap/below_poverty_no_snap",
        "/house/52/snap/below_poverty_no_snap",
        "/senate/26/snap/below_poverty_no_snap",
        "/other/22/snap/below_poverty_no_snap",
        "/house/no/snap/below_poverty_no_snap",
        "/house/22/snap/below_poverty_no_snap?preview=invalid",
        "/house/22/snap%253Fother/below_poverty_no_snap",
    ],
)
def test_invalid_or_unmapped_permalink_is_404(suffix: str) -> None:
    query = "" if "?" in suffix else "?preview=1"
    assert TestClient(app).get("/match" + suffix + query).status_code == 404


@pytest.mark.parametrize("review_status,expected", [("reviewed", 200), ("rejected", 404)])
def test_permalink_rejects_mapping_before_matching(
    review_status: str,
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
    matching_store: Path,
) -> None:
    mapping = next(
        m
        for m in load_mappings()
        if m.program_id == "snap" and m.population_id == "below_poverty_no_snap"
    ).model_copy(update={"review_status": review_status})
    monkeypatch.setattr(import_module("app.web.matches"), "load_mappings", lambda: (mapping,))
    # Observe the route boundary so the tool's own rejection filter cannot mask a regression.
    with patch.object(
        DistrictMatches, "get_matches", autospec=True, side_effect=DistrictMatches.get_matches
    ) as get_matches:
        assert TestClient(app).get(PATH + "?preview=1").status_code == expected
        assert get_matches.call_count == (1 if review_status == "reviewed" else 0)


@pytest.mark.parametrize(
    "policy,query,expected",
    [
        ("off", "", 404),
        ("off", "?preview=1", 404),
        ("preview", "", 404),
        ("preview", "?preview=0", 404),
        ("preview", "?preview=1", 200),
        ("on", "", 200),
    ],
)
def test_matching_feature_gates_before_data_access(
    policy: str,
    query: str,
    expected: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    matching_store: Path,
) -> None:
    import app.features as features

    config = tmp_path / "features.toml"
    config.write_text(f'matches = "{policy}"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", config)
    if expected == 404:

        def no_read(*args: object, **kwargs: object) -> None:
            raise AssertionError("disabled match must not read data")

        monkeypatch.setattr(DistrictMatches, "get_matches", no_read)
        monkeypatch.setattr(import_module("app.web.matches"), "load_catalog", no_read)
    assert TestClient(app).get(PATH + query).status_code == expected


def test_retired_id_survives_rename_without_current_referral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = import_module("app.web.matches")
    catalog = load_catalog(ROOT / "data/programs.yaml")
    snap = next(p for p in catalog if p.id == "snap")
    snap.name = "Renamed food assistance"
    snap.retired = date(2026, 10, 29)

    def retired_catalog(path: Path) -> list[Program]:
        return catalog

    monkeypatch.setattr(route, "load_catalog", retired_catalog)
    response = TestClient(app).get(PATH + "?preview=1")
    assert response.status_code == 200
    assert "Renamed food assistance" in response.text
    assert "no longer offered" in response.text
    assert "Aloha United Way 211" in response.text
    assert "Program may help" not in response.text
    assert (
        TestClient(app)
        .get(PATH.replace("snap/", "renamed-food-assistance/") + "?preview=1")
        .status_code
        == 404
    )


def test_unavailable_measurement_remains_a_card(
    matching_store: Path,
) -> None:
    with sqlite3.connect(matching_store) as db:
        db.execute("DELETE FROM facts WHERE variable LIKE 'S1810%'")
    response = TestClient(app).get("/match/house/22/hawaii-able/disability?preview=1")
    assert response.status_code == 200
    assert "Not available" in response.text
    assert "insufficient" in response.text
    assert "S1810_C02_001E" in response.text
    assert "Comparable uptake unavailable" in response.text


def test_card_prints_with_citations_and_has_no_serious_axe_violations(
    page: Page,
    matching_store: Path,
) -> None:
    response = TestClient(app).get(PATH + "?preview=1")
    assert response.status_code == 200
    page.set_content(response.text)
    page.add_style_tag(path=str(ROOT / "static/tokens.css"))
    page.add_style_tag(path=str(ROOT / "static/site.css"))
    assert axe_problems(page) == []
    page.emulate_media(media="print")
    assert page.locator("article.case").is_visible()
    citations = page.locator(".case-citation")
    assert citations.count() > 0
    for citation in citations.all():
        assert citation.is_visible()
        assert "2020–2024" in citation.inner_text()
        assert "house:15:022:2022" in citation.inner_text()
