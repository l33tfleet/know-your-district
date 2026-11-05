"""Credential failures must never be published as Census unavailability."""

from pathlib import Path

from etl.outreach import OUTPUT, Source


def test_published_source_has_no_invented_credential_annotations() -> None:
    source = OUTPUT / "source.json"
    if not source.exists():
        # An unavailable credential blocks publication, not Census observations.
        assert not any(OUTPUT.glob("facts.*"))
        assert not (OUTPUT / "provenance.json").exists()
        return
    capture = Source.model_validate_json(source.read_bytes())
    for batch in capture.batches.values():
        for row in batch.rows:
            for variable in ("B22003_006EA", "B22003_006MA"):
                annotation = row[variable] or ""
                assert "Missing Key" not in annotation
                assert "CENSUS_API_KEY" not in annotation


def test_credential_failure_does_not_create_publication(tmp_path: Path) -> None:
    import pytest

    from etl.census import CensusClient, CensusError
    from etl.outreach import build

    with pytest.MonkeyPatch.context() as monkeypatch:

        def fail(client: CensusClient, url: str, params: dict[str, str]) -> object:
            raise CensusError("Census HTTP request failed or returned invalid JSON")

        monkeypatch.setattr(CensusClient, "_get", fail)
        output = tmp_path / "unpublished"
        with pytest.raises(CensusError, match="Census HTTP request failed"):
            build(output)
        assert not output.exists()
