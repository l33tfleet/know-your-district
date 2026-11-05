"""#333: profile extensions stay separate and statistics require exact fact keys."""

import hashlib
import importlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app import features
from app.brief import discover
from app.facts import FactStore
from app.main import app, templates
from app.page_state import PageState
from etl.boundaries import DistrictId
from etl.programs import Program, load_catalog
from tests.regressions.test_148_contracts import extended
from tests.regressions.test_wo97_brief_page import Tree, build_db, row

__all__ = ["extended"]
ROOT = Path(__file__).resolve().parents[2]
DISTRICT = DistrictId(chamber="house", district="22")


def render(program: Program, monkeypatch: pytest.MonkeyPatch) -> str:
    module = importlib.import_module("app.sections.35_profiles")

    def catalog(path: Path) -> list[Program]:
        return [program]

    monkeypatch.setattr(module, "load_catalog", catalog)
    return templates.env.get_template("sections/35-profiles.html").render(
        section=module.context(PageState(district=DISTRICT)),
        copy=module.section_copy("profiles"),
    )


def test_legacy_serialization_and_one_extended_pilot() -> None:
    programs = load_catalog(ROOT / "data/programs.yaml")
    raw = yaml.safe_load((ROOT / "data/programs.yaml").read_text())
    assert len(programs) == 3
    for program, original, digest in zip(
        programs[:2],
        raw[:2],
        [
            "04075a43b898878c8222428be3257c755dd7c835048ef45c57f0991231f64e91",
            "426cad0a88be43a88f31406f751f201ed8054d44801c15045d0eab5475541e7c",
        ],
        strict=True,
    ):
        assert set(program.model_dump()) == set(original) | {"retired"}
        assert set(json.loads(program.model_dump_json())) == set(original) | {"retired"}
        assert not {"rules", "next_steps", "enrichment"} & program.model_dump().keys()
        serialized = json.dumps(program.model_dump(mode="json"), sort_keys=True)
        assert hashlib.sha256(serialized.encode()).hexdigest() == digest
    pilot = programs[-1]
    assert pilot.rules and pilot.next_steps and pilot.enrichment
    assert Program.model_validate_json(pilot.model_dump_json()) == pilot
    for ref in pilot.enrichment.fact_references:
        assert FactStore.default().get([(ref.variable, ref.geography)], ref.vintage)


def test_complete_render_uses_only_fact_evidence(
    extended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extended["enrichment"]["fact_references"][0]["geography"] = DISTRICT.fact_key
    extended["enrichment"]["stats"][0].update(
        value=987654321,
        moe=987654322,
        label="POISON_LABEL",
        source="POISON_SOURCE",
        method="POISON_METHOD",
        unit="POISON_UNIT",
        geography="POISON_GEOGRAPHY",
        table_id="POISON_TABLE",
        cell="POISON_CELL",
        vintage="POISON_VINTAGE",
        source_url="https://example.org/POISON_URL",
    )
    fact = row("population", DISTRICT.fact_key, 12345, 321).model_copy(
        update={"variable": "B22003_006E", "table_id": "B22003", "label": "Fact label"}
    )
    path = tmp_path / "facts.db"
    build_db(path, [fact])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    html = render(Program.model_validate(extended), monkeypatch)
    tree = Tree()
    tree.feed(html)
    text = tree.root.text
    for expected in (
        "Fact label",
        "12,345",
        "321",
        "reliable",
        "margin of error (90%)",
        fact.source,
        fact.table_id,
        fact.vintage,
        fact.geography,
        fact.method,
        "Hawaiʻi",
        "People purchasing and preparing meals together",
        "Hawaiʻi HHS",
        "Monthly",
        "Agency household and income conditions apply",
        "The agency reviews exceptions",
        "2026-01-01",
        "2026-10-01",
        "2026-10-02",
        "Unknown",
        "2026-10-25",
        "Catalog maintainers",
        "2026-11-25",
        "Illustrative fixture",
        "CC-BY-4.0",
        "Population context",
        "not an eligibility or nonparticipation estimate",
        "Aloha United Way 211",
    ):
        assert expected in text
    for poison in ("987654321", "987654322", "POISON_"):
        assert poison not in html
    assert tree.root.one("img").attrs["alt"] == "Coast"
    hrefs = [a.attrs["href"] for a in tree.root.find_all("a")]
    assert fact.endpoint in hrefs
    assert "https://creativecommons.org/licenses/by/4.0/" in hrefs
    assert "https://www.auw211.org/" in hrefs


@pytest.mark.parametrize("mismatch", ["variable", "geography", "vintage", "missing", "null"])
def test_unmatched_observations_never_fall_back_to_yaml(
    extended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    ref = extended["enrichment"]["fact_references"][0]
    ref["geography"] = DISTRICT.fact_key
    fact = row("population", DISTRICT.fact_key, 12345, 321).model_copy(
        update={"variable": ref["variable"]}
    )
    if mismatch == "variable":
        fact = fact.model_copy(update={"variable": "B01003_001E"})
    elif mismatch == "geography":
        fact = fact.model_copy(update={"geography": "house:15:001:2022"})
    elif mismatch == "vintage":
        fact = fact.model_copy(update={"vintage": "2019–2023"})
    elif mismatch == "null":
        fact = row("population", DISTRICT.fact_key, None, None).model_copy(
            update={"variable": ref["variable"]}
        )
    path = tmp_path / "facts.db"
    if mismatch != "missing":
        build_db(path, [fact])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    html = render(Program.model_validate(extended), monkeypatch)
    assert "not available" in html
    assert "12,345" not in html
    assert ">120" not in html
    assert "Households" not in html


@pytest.mark.parametrize("geography", ["house:15:001:2022", "senate:15:022:2022"])
def test_other_districts_are_not_local_observations(
    extended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, geography: str
) -> None:
    ref = extended["enrichment"]["fact_references"][0]
    ref["geography"] = geography
    fact = row("population", geography, 87654321, 321).model_copy(
        update={"variable": ref["variable"]}
    )
    path = tmp_path / "facts.db"
    build_db(path, [fact])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    html = render(Program.model_validate(extended), monkeypatch)
    assert "87,654,321" not in html
    assert "not available" in html


@pytest.mark.parametrize("geography", ["county:15:003", "state:15"])
def test_broader_facts_are_explicit_context(
    extended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, geography: str
) -> None:
    ref = extended["enrichment"]["fact_references"][0]
    ref["geography"] = geography
    fact = row("population", geography, 12345, None).model_copy(
        update={"variable": ref["variable"]}
    )
    path = tmp_path / "facts.db"
    build_db(path, [fact])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    html = render(Program.model_validate(extended), monkeypatch)
    assert "County/state context" in html
    assert "12,345" in html
    assert "no margin of error published" in html
    assert "use with caution" in html


def test_optional_profiles_dates_and_permission(
    extended: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    program = Program.model_validate(extended)
    assert program.rules and program.enrichment
    program.rules.enacted_date = None
    program.rules.effective_date = None
    program.rules.open_date = None
    media = program.enrichment.media[0].model_dump(mode="json")
    media.update(
        licence="permission",
        licence_url=None,
        permission={
            "record_url": "https://example.org/permission",
            "date": "2026-10-25",
            "permits_reuse": True,
        },
    )
    from etl.programs.enrichment import Media

    program.enrichment.media = [Media.model_validate(media)]
    html = render(program, monkeypatch)
    assert html.count("Unknown") >= 4
    assert "No date" not in html
    assert "https://example.org/permission" in html
    program.rules = None
    program.next_steps = None
    program.enrichment.fact_references = []
    assert "not available" in render(program, monkeypatch)
    program.enrichment = None
    assert program.name not in render(program, monkeypatch)
    program = Program.model_validate(extended)
    program.retired = date(2026, 10, 1)
    assert program.name not in render(program, monkeypatch)


@pytest.mark.parametrize("chamber,number", [("house", "22"), ("senate", "5")])
def test_briefs_include_screen_only_profile(
    chamber: str, number: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = tmp_path / "features.toml"
    policy.write_text('outreach = "on"\nprofiles = "on"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", policy)
    response = TestClient(app).get(f"/brief/{chamber}/{number}")
    assert response.status_code == 200
    assert 'class="profiles"' in response.text
    assert "Not on the printout" in response.text
    assert not next(s for s in discover() if s.name == "profiles").printable


def test_profiles_default_off_preserves_brief_print_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = tmp_path / "features.toml"
    policy.write_text('outreach = "off"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", policy)
    response = TestClient(app).get("/brief/house/22")
    assert response.status_code == 200
    assert 'class="profiles"' not in response.text
    assert 'class="screen-only"' not in response.text


def test_pilot_urls_follow_catalog_link_policy() -> None:
    from etl.programs.links import LinkResponse, check_catalog

    programs = load_catalog(ROOT / "data/programs.yaml")
    report = check_catalog(
        programs, get=lambda _url, _timeout: LinkResponse(200), today=lambda: date(2026, 11, 5)
    )
    assert not report.failures


def test_pilot_profile_does_not_claim_comparisons(monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = load_catalog(ROOT / "data/programs.yaml")[-1]
    tree = Tree()
    tree.feed(render(pilot, monkeypatch))
    text = f" {tree.root.text.lower()} "
    for word in ("higher", "lower", "above", "below"):
        assert f" {word} " not in text
