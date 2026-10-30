"""#209: registry references and the evidence ceiling for program mappings."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.populations import load_populations
from etl.programs import load_catalog
from etl.programs.mappings import ProgramMapping, load_mappings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mapping() -> dict[str, Any]:
    return {
        "population_id": "below_poverty_no_snap",
        "program_id": "snap",
        "relevance": "SNAP may help with food costs; this is an outreach signal only.",
        "observed_conditions": ["Household poverty and self-reported SNAP nonreceipt jointly."],
        "unobserved_conditions": ["Current income, assistance unit and nonfinancial rules."],
        "claim": "relevant_need",
        "review_status": "pending",
    }


@pytest.fixture
def modeling() -> dict[str, Any]:
    # Synthetic evidence: exercises the contract, never a shipped eligibility model.
    return {
        "method": "Synthetic aggregate rule simulation.",
        "rule_source": "https://example.org/rules",
        "assumptions": ["Synthetic imputation of unobserved conditions."],
        "validation": "Synthetic holdout comparison documented in the model report.",
        "evidence_url": "https://example.org/model-report",
    }


@pytest.fixture
def comparability() -> dict[str, Any]:
    return {
        "participation_source": "https://example.org/participation",
        "geography": "Synthetic matching native district boundaries.",
        "period": "Synthetic matching reference periods.",
        "unit": "Synthetic matching assistance units and population definitions.",
        "overlap": "Synthetic deduplication and eligibility overlap assessment.",
        "coverage": "Synthetic coverage and suppression assessment.",
    }


def write_mappings(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return path


def test_pending_relevance_mapping_passes(tmp_path: Path, mapping: dict[str, Any]) -> None:
    result = load_mappings(write_mappings(tmp_path, [mapping]))
    assert result[0].review_status == "pending"
    assert result[0].claim == "relevant_need"
    assert result[0].unobserved_conditions


def test_committed_mappings_use_registry_ids() -> None:
    mappings = load_mappings()
    populations = {p.id for p in load_populations().populations}
    programs = {p.id for p in load_catalog(ROOT / "data/programs.yaml")}
    assert mappings
    assert all(m.population_id in populations and m.program_id in programs for m in mappings)
    assert all(m.claim == "relevant_need" and m.review_status == "pending" for m in mappings)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("program_id", "unknown", "Unknown program ID: unknown"),
        ("program_id", "Supplemental Nutrition Assistance Program (SNAP)", "program_id"),
        ("population_id", "unknown", "Unknown population ID: unknown"),
        ("population_id", "Households below poverty reporting no SNAP", "population_id"),
    ],
)
def test_unknown_references_fail(
    tmp_path: Path, mapping: dict[str, Any], field: str, value: str, error: str
) -> None:
    mapping[field] = value
    with pytest.raises(ValueError, match=error):
        load_mappings(write_mappings(tmp_path, [mapping]))


def test_program_rename_preserves_mapping(tmp_path: Path, mapping: dict[str, Any]) -> None:
    programs = [p.model_dump(mode="json") for p in load_catalog(ROOT / "data/programs.yaml")]
    programs[0]["name"] = "Changed display name"
    catalog = tmp_path / "programs.yaml"
    catalog.write_text(yaml.safe_dump(programs), encoding="utf-8")
    assert load_mappings(write_mappings(tmp_path, [mapping]), programs_path=catalog)[0].program_id


@pytest.mark.parametrize("claim", ["modeled_eligibility", "comparable_nonparticipation"])
def test_stronger_claim_requires_modeling(mapping: dict[str, Any], claim: str) -> None:
    mapping["claim"] = claim
    with pytest.raises(ValueError, match="modeling evidence is required"):
        ProgramMapping.model_validate(mapping)


def test_nonparticipation_requires_comparability(
    mapping: dict[str, Any], modeling: dict[str, Any]
) -> None:
    mapping.update(claim="comparable_nonparticipation", modeling_evidence=modeling)
    with pytest.raises(ValueError, match="comparability evidence is required"):
        ProgramMapping.model_validate(mapping)


def test_evidenced_claims_pass(
    tmp_path: Path,
    mapping: dict[str, Any],
    modeling: dict[str, Any],
    comparability: dict[str, Any],
) -> None:
    mapping.update(claim="modeled_eligibility", modeling_evidence=modeling)
    assert load_mappings(write_mappings(tmp_path, [mapping]))[0].claim == "modeled_eligibility"
    mapping.update(claim="comparable_nonparticipation", comparability_evidence=comparability)
    assert load_mappings(write_mappings(tmp_path, [mapping]))[0].claim == mapping["claim"]


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
def test_mapping_requires_explicit_contract(mapping: dict[str, Any], field: str) -> None:
    del mapping[field]
    with pytest.raises(ValueError, match=field):
        ProgramMapping.model_validate(mapping)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claim", "eligible"),
        ("review_status", "verified-ish"),
        ("relevance", "  "),
        ("program_id", "snap?x"),
        ("population_id", "../kupuna"),
        ("relevance", "text\x00control"),
        ("unknown_field", "ignored?"),
    ],
)
def test_invalid_contract_fails(mapping: dict[str, Any], field: str, value: str) -> None:
    mapping[field] = value
    with pytest.raises(ValueError, match=field):
        ProgramMapping.model_validate(mapping)


@pytest.mark.parametrize(
    ("evidence", "field"),
    [
        ("modeling_evidence", "method"),
        ("modeling_evidence", "rule_source"),
        ("modeling_evidence", "assumptions"),
        ("modeling_evidence", "validation"),
        ("modeling_evidence", "evidence_url"),
        ("comparability_evidence", "participation_source"),
        ("comparability_evidence", "geography"),
        ("comparability_evidence", "period"),
        ("comparability_evidence", "unit"),
        ("comparability_evidence", "overlap"),
        ("comparability_evidence", "coverage"),
    ],
)
def test_incomplete_evidence_fails(
    mapping: dict[str, Any],
    modeling: dict[str, Any],
    comparability: dict[str, Any],
    evidence: str,
    field: str,
) -> None:
    mapping.update(
        claim="comparable_nonparticipation",
        modeling_evidence=modeling,
        comparability_evidence=comparability,
    )
    del mapping[evidence][field]
    with pytest.raises(ValueError, match=field):
        ProgramMapping.model_validate(mapping)


def test_duplicate_mapping_fails(tmp_path: Path, mapping: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Duplicate mapping"):
        load_mappings(write_mappings(tmp_path, [mapping, mapping]))


@pytest.mark.parametrize("content", ["[broken", "{}", "[]"])
def test_invalid_yaml_or_document_fails(tmp_path: Path, content: str) -> None:
    path = tmp_path / "mappings.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_mappings(path)
