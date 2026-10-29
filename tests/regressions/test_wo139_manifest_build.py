"""WO177: manifest-backed compatibility and separately staged source builds."""

import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml

from app.sources import SOURCE_PATH, load_source
from etl.census import CensusClient, CensusError, load_config
from tests.regressions.test_wo118_facts_build import recorded_client as recorded_client
from tests.regressions.test_wo118_facts_build import snapshot

DIGEST = "f020a03f1cc82d4670af2833cd367c476aa51434cf2e6216fc6d1313d7cc7294"


def manifests(directory: Path) -> Path:
    directory.mkdir()
    (directory / "acs.yaml").write_bytes(SOURCE_PATH.read_bytes())
    data = load_source().model_dump(mode="json")
    data["indicators"] = data["indicators"][:1]
    (directory / "additional.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return directory


def test_adapter_uses_each_manifest() -> None:
    from etl.source_build import adapt_source

    source = load_source()
    indicators, config = adapt_source(source)
    old_config = load_config()
    assert config.year == old_config.year
    assert config.vintage == old_config.vintage
    assert config.base_url == old_config.base_url.format(year=old_config.year)
    assert config.state == old_config.state
    assert config.vintages == {str(config.year): old_config.vintages[str(config.year)]}
    assert config.labels == {k: v.format(year=config.year) for k, v in old_config.labels.items()}
    assert tuple(indicators) == tuple(i.id for i in source.indicators)
    for group in source.indicators:
        assert indicators[group.id].variables == tuple(v.id for v in group.variables)
        assert indicators[group.id].endpoint == group.endpoint
    data = source.model_dump(mode="json")
    data["indicators"] = data["indicators"][10:11]
    subset = type(source).model_validate(data)
    groups, config = adapt_source(subset)
    assert tuple(groups) == ("rent_burden",)
    assert set(config.labels) == {"DP04_0141PE", "DP04_0142PE"}


def test_discovered_build_preserves_baseline_digest_and_separates_sources(
    tmp_path: Path, recorded_client: CensusClient
) -> None:
    from etl.build import check
    from etl.source_build import build_sources

    sources = manifests(tmp_path / "sources")
    output = tmp_path / "output"
    assert build_sources(sources, output) == 324
    assert check(output)
    assert check(output / "additional")
    assert hashlib.sha256((output / "facts.tsv").read_bytes()).hexdigest() == DIGEST
    assert len((output / "additional/facts.tsv").read_text().splitlines()) == 82


@pytest.mark.parametrize("failure", ["label", "manifest", "missing_baseline"])
def test_discovery_failure_preserves_every_published_source(
    tmp_path: Path, recorded_client: CensusClient, failure: str
) -> None:
    from etl.source_build import build_sources

    sources = manifests(tmp_path / "sources")
    output = tmp_path / "output"
    build_sources(sources, output)
    before = snapshot(output), snapshot(output / "additional")
    if failure == "label":
        path = sources / "additional.yaml"
        path.write_text(path.read_text().replace("Estimate!!Total", "Wrong label"))
        error, message = CensusError, "Label mismatch"
    elif failure == "manifest":
        (sources / "additional.yaml").write_text("name: incomplete")
        error, message = ValueError, "validation errors"
    else:
        (sources / "acs.yaml").unlink()
        error, message = FileNotFoundError, "acs.yaml"
    with pytest.raises(error, match=message):
        build_sources(sources, output)
    assert (snapshot(output), snapshot(output / "additional")) == before
    assert {p.name for p in output.iterdir()} == {*before[0], "additional"}


def test_manifest_cli_preview_build_and_check(
    tmp_path: Path, recorded_client: CensusClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etl.build import main

    sources = manifests(tmp_path / "sources")
    output = tmp_path / "output"
    args = ["etl.build", "--sources", str(sources), "--output", str(output)]
    monkeypatch.setattr("sys.argv", [*args, "--dry-run"])
    assert main() == 0
    assert not output.exists()
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    monkeypatch.setattr("sys.argv", [*args, "--check"])
    assert main() == 0
    (output / "additional/facts.tsv").write_text("corrupt")
    assert main() == 1


def test_make_data_explicitly_discovers_manifests() -> None:
    result = subprocess.run(["make", "-n", "data"], check=True, capture_output=True, text=True)
    assert "python -m etl.build --sources" in result.stdout
    assert "data/sources" in result.stdout


def test_invalid_source_artifact_name_preserves_publication(
    tmp_path: Path, recorded_client: CensusClient
) -> None:
    from etl.source_build import build_sources

    sources = manifests(tmp_path / "sources")
    (sources / "additional.yaml").rename(sources / "bad-name.yaml")
    with pytest.raises(ValueError, match="string_pattern_mismatch"):
        build_sources(sources, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_manifest_and_legacy_config_are_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    from etl.build import main

    monkeypatch.setattr(
        "sys.argv", ["etl.build", "--sources", "data/sources", "--config", "config.toml"]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
