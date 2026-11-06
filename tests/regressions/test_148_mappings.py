"""#334: a non-poverty audience match preserves its measure and claim ceiling."""

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app import features
from app.facts import FactStore
from app.main import app
from app.models import Fact
from app.populations import load_populations
from etl.programs.mappings import ProgramMapping, load_mappings


@pytest.fixture(autouse=True)
def matches_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = tmp_path / "features.toml"
    policy.write_text('outreach = "on"\nmatches = "on"\n', encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", policy)


def test_disabled_matches_preserve_brief_and_skip_mapping_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = tmp_path / "disabled.toml"
    policy.write_text('outreach = "off"\n', encoding="utf-8")
    monkeypatch.setattr(features, "FEATURES_PATH", policy)
    section = import_module("app.sections.36_matches")

    def unexpected_load() -> None:
        pytest.fail("Disabled matches must not load mappings")

    monkeypatch.setattr(section, "load_mappings", unexpected_load)
    response = TestClient(app).get("/brief/house/22")
    assert response.status_code == 200
    assert 'class="matches"' not in response.text
    assert 'class="screen-only"' not in response.text


def test_matches_template_keeps_wording_in_section_context() -> None:
    # The work order excludes app/copy.yaml, as for the population section.
    import re

    path = Path(__file__).resolve().parents[2] / "templates/sections/36-matches.html"
    source = re.sub(r"{#.*?#}|{%.*?%}|{{.*?}}", " ", path.read_text(), flags=re.S)
    source = re.sub(r"<!--.*?-->|<[^>]*>|&[a-z]+;", " ", source, flags=re.S)
    assert not re.search(r"[^\W\d_]", source)


def able_mapping() -> ProgramMapping:
    return next(m for m in load_mappings() if m.program_id == "hawaii-able")


def test_nonpoverty_mapping_preserves_all_fields_and_measure() -> None:
    mapping = able_mapping()
    assert mapping.population_id == "disability"
    assert "may help" in mapping.relevance
    assert mapping.observed_conditions
    assert any("onset" in c.lower() for c in mapping.unobserved_conditions)
    assert any("certification" in c.lower() for c in mapping.unobserved_conditions)
    assert any("enrollment" in c.lower() for c in mapping.unobserved_conditions)
    assert mapping.claim == "relevant_need"
    assert mapping.review_status == "pending"
    assert mapping.modeling_evidence is None
    assert mapping.comparability_evidence is None
    population = next(p for p in load_populations().populations if p.id == mapping.population_id)
    assert population.numerator == ("S1810_C02_001E",)
    assert population.denominator == ("S1810_C01_001E",)
    assert population.unit == "persons"


@pytest.mark.parametrize(
    "field",
    [
        "population_id",
        "program_id",
        "relevance",
        "observed_conditions",
        "unobserved_conditions",
        "claim",
        "review_status",
    ],
)
def test_match_fields_are_required(field: str) -> None:
    raw = able_mapping().model_dump(mode="json")
    del raw[field]
    with pytest.raises(ValueError, match=field):
        ProgramMapping.model_validate(raw)


@pytest.mark.parametrize("review", ["pending", "reviewed", "rejected"])
@pytest.mark.parametrize("claim", ["modeled_eligibility", "comparable_nonparticipation"])
def test_expert_review_cannot_replace_claim_evidence(review: str, claim: str) -> None:
    raw = able_mapping().model_dump(mode="json")
    raw.update(review_status=review, claim=claim)
    with pytest.raises(ValueError, match="modeling evidence is required"):
        ProgramMapping.model_validate(raw)


@pytest.mark.parametrize("field", ["population_id", "program_id"])
def test_unknown_match_ids_fail_clearly(tmp_path: Path, field: str) -> None:
    raw = able_mapping().model_dump(mode="json")
    raw[field] = "unknown"
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump([raw]), encoding="utf-8")
    with pytest.raises(ValueError, match=r"Unknown .* ID: unknown"):
        load_mappings(path)


@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_brief_renders_nonpoverty_match_with_limits(
    chamber: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "absent.db"))
    response = TestClient(app).get(f"/brief/{chamber}/22")
    assert response.status_code == 200
    html = response.text
    assert 'data-match="disability:hawaii-able"' in html
    for text in (
        "People with a disability",
        "Relevant need only",
        "Program-expert review: pending",
        "Disability onset",
        "certification",
        "enrollment",
        "S1810_C02_001E",
        "Civilian noninstitutionalized population",
        "Not available",
        "not available",
        "https://www.ssa.gov/ssi/spotlights/spot-able.html",
        "https://www.auw211.org/",
        "agency decides eligibility",
    ):
        assert text in html


def test_rejected_matches_are_not_referred(monkeypatch: pytest.MonkeyPatch) -> None:
    section = import_module("app.sections.36_matches")
    rejected = able_mapping().model_copy(update={"review_status": "rejected"})
    monkeypatch.setattr(section, "load_mappings", lambda: (rejected,))
    html = TestClient(app).get("/brief/house/22").text
    assert 'data-match="disability:hawaii-able"' not in html


def test_duplicate_yaml_claim_cannot_silently_downgrade_validation(tmp_path: Path) -> None:
    raw: dict[str, Any] = {
        "population_id": "below_poverty_no_snap",
        "program_id": "snap",
        "relevance": "SNAP may help.",
        "observed_conditions": [],
        "unobserved_conditions": [],
        "claim": "modeled_eligibility",
        "review_status": "pending",
    }
    path = tmp_path / "mappings.yaml"
    content = yaml.safe_dump([raw], sort_keys=False)
    path.write_text(content + "  claim: relevant_need\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML key: claim"):
        load_mappings(path)


def test_match_count_retains_fact_citation_and_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Synthetic observation: validates rendering, never asserts a published district count.
    fact = Fact(
        variable="S1810_C02_001E",
        geography="house:15:022:2022",
        vintage="2020–2024",
        value=1234,
        moe=234,
        cv=(234 / 1.645) / 1234,
        reliability="reliable",
        source="Synthetic Census fixture",
        table_id="S1810",
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5/subject",
        label="Synthetic disability",
    )

    def get(*args: object) -> dict[tuple[str, str], Fact]:
        return {(fact.variable, fact.geography): fact}

    monkeypatch.setattr(FactStore, "get", get)
    html = TestClient(app).get("/brief/house/22").text
    match = html.split('data-match="disability:hawaii-able"', 1)[1].split("</article>", 1)[0]
    for text in (
        "1,234 persons",
        "±234",
        "reliable",
        "Synthetic Census fixture",
        "S1810",
        "S1810_C02_001E",
        "2020–2024",
        "house:15:022:2022",
        "published estimate and 90% margin of error",
        fact.endpoint,
    ):
        assert text in match
