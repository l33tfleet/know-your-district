"""WO #37: licence/privacy evidence must reflect the implemented ACS fetcher."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_licences_describe_current_acs_fetching_and_storage() -> None:
    data_doc = (ROOT / "docs/data.md").read_text(encoding="utf-8")
    licences = data_doc.split("## Data licences\n", 1)[1].split("\n## ", 1)[0]
    assert "../etl/census.py" in licences
    assert "../config.toml" in licences
    assert "fetches" in licences and "2020–2024" in licences
    assert "schema.sql" in licences
    assert "no built database is committed" in licences
    assert "loads and distributes no datasets" not in licences
    assert "contains only its README" not in licences


def test_privacy_note_links_implemented_etl_evidence() -> None:
    note = (ROOT / "docs/security-privacy.md").read_text(encoding="utf-8")
    assert "../etl/census.py" in note
    assert "../etl/__init__.py" not in note
