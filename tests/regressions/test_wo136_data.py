"""WO159: published SNAP coverage, independent district oracle and offline evidence."""

import shutil
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/regressions/fixtures/wo136_snap.json"


def test_published_snap_artifacts() -> None:
    from scripts.independent_snap import validate_artifacts

    validate_artifacts(ROOT / "data/snap", GOLDEN)


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("DELETE FROM facts WHERE geography = 'house:15:051:2022'", "geography set"),
        (
            "UPDATE facts SET geography = 'county:15:005' WHERE geography = 'county:15:009'",
            "geography set",
        ),
        ("UPDATE facts SET variable = 'B22003_003E'", "cell provenance"),
        ("UPDATE facts SET vintage = '2019–2023'", "cell provenance"),
        ("UPDATE facts SET label = 'wrong meaning'", "cell provenance"),
        ("UPDATE facts SET table_id = 'B22010'", "cell provenance"),
        ("UPDATE facts SET source = 'Unknown publisher'", "cell provenance"),
        ("UPDATE facts SET method = 'modeled eligibility'", "cell provenance"),
        ("UPDATE facts SET endpoint = 'https://example.org'", "cell provenance"),
        (
            "UPDATE facts SET value = value + 1 WHERE geography = 'house:15:001:2022'",
            "golden estimate/MOE",
        ),
        (
            "UPDATE facts SET moe = moe + 1 WHERE geography = 'house:15:001:2022'",
            "golden estimate/MOE",
        ),
    ],
)
def test_snap_rejects_wrong_published_facts(tmp_path: Path, sql: str, error: str) -> None:
    from scripts.independent_snap import validate_facts

    database = tmp_path / "facts.db"
    shutil.copyfile(ROOT / "data/snap/facts.db", database)
    with sqlite3.connect(database) as db:
        db.execute(sql)
    with pytest.raises(ValueError, match=error):
        validate_facts(database, GOLDEN)


def test_snap_requires_artifacts(tmp_path: Path) -> None:
    from scripts.independent_snap import validate_artifacts

    with pytest.raises(ValueError, match="Missing SNAP artifacts"):
        validate_artifacts(tmp_path, GOLDEN)


def test_snap_rejects_changed_evidence(tmp_path: Path) -> None:
    from scripts.independent_snap import validate_artifacts

    output = tmp_path / "snap"
    shutil.copytree(ROOT / "data/snap", output)
    (output / "evidence/dhs-snap.html").write_text("changed")
    with pytest.raises(ValueError, match="Evidence digest mismatch"):
        validate_artifacts(output, GOLDEN)


def test_summary_replay_preserves_core_and_preview(tmp_path: Path) -> None:
    from scripts.independent_snap import build_summary

    output = tmp_path / "snap"
    output.mkdir()
    shutil.copytree(ROOT / "data/snap/evidence", output / "evidence")
    core_before = (ROOT / "data/facts.db").read_bytes()
    build_summary(output, dry_run=True)
    assert not (output / "facts.db").exists()
    build_summary(output, dry_run=False)
    from scripts.independent_snap import validate_facts

    validate_facts(output / "facts.db", GOLDEN)
    assert (output / "facts.tsv").read_bytes() == (ROOT / "data/snap/facts.tsv").read_bytes()
    assert (ROOT / "data/facts.db").read_bytes() == core_before


@pytest.mark.parametrize("mutation", ["header", "missing"])
def test_summary_replay_rejects_incomplete_source(tmp_path: Path, mutation: str) -> None:
    from scripts.independent_snap import build_summary

    output = tmp_path / "snap"
    shutil.copytree(ROOT / "data/snap/evidence", output / "evidence")
    path = output / "evidence/b22003-hawaii.dat"
    lines = path.read_text().splitlines(keepends=True)
    if mutation == "header":
        lines[0] = lines[0].replace("B22003_E006", "B22003_E999")
    else:
        lines = [line for line in lines if not line.startswith("620L900US15051|")]
    path.write_text("".join(lines))
    with pytest.raises(
        ValueError,
        match="Summary header mismatch"
        if mutation == "header"
        else "Incomplete Census geography set",
    ):
        build_summary(output, dry_run=False)
    assert not (output / "facts.db").exists()


def test_fresh_oracle_reads_raw_census_line_without_etl_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import independent_snap as oracle

    evidence = ROOT / "data/snap/evidence"
    responses = {
        oracle.METADATA_URL: (evidence / "census-metadata.json").read_bytes(),
        oracle.SUMMARY_URL: (evidence / "b22003-hawaii.dat").read_bytes(),
    }
    monkeypatch.setattr(oracle, "request", responses.__getitem__)
    fresh = oracle.fetch()
    saved = oracle.Golden.model_validate_json(GOLDEN.read_bytes())
    assert fresh.row == saved.row
    assert oracle.golden_values(fresh) == oracle.golden_values(saved)


@pytest.mark.parametrize(
    ("field", "replacement", "error"),
    [
        ("source_url", "https://example.org", "metadata/request mismatch"),
        ("metadata_url", "https://example.org", "metadata/request mismatch"),
        ("label", "Receipt rather than nonreceipt", "metadata/request mismatch"),
        ("attributes", "B22003_006EA,B22003_006MA", "metadata/request mismatch"),
        ("header", "B22003_E007", "response mismatch"),
        ("geography", "620L900US15002", "response mismatch"),
        ("value", "-666666666", "numeric cell unavailable"),
        ("moe", "NaN", "numeric cell unavailable"),
    ],
)
def test_golden_rejects_wrong_source_or_unavailable_cells(
    field: str, replacement: str, error: str
) -> None:
    from scripts.independent_snap import Golden, golden_values

    saved = Golden.model_validate_json(GOLDEN.read_bytes())
    if field in {"source_url", "metadata_url"}:
        saved = saved.model_copy(update={field: replacement})
    elif field in {"label", "attributes"}:
        saved.metadata = saved.metadata.model_copy(update={field: replacement})
    elif field == "header":
        saved.header[11] = replacement
    else:
        saved.row[{"geography": 0, "value": 11, "moe": 12}[field]] = replacement
    with pytest.raises(ValueError, match=error):
        golden_values(saved)


def test_dated_referrals_match_official_contact_evidence() -> None:
    import json

    output = ROOT / "data/snap"
    referrals = json.loads((output / "referrals.json").read_bytes())
    assert referrals["verified_on"] == "2026-10-28"
    assert referrals["rules"]["income_chart_effective_on"] == "2026-10-01"
    assert referrals["outreach_effective_on"] == "2026-10-01"
    assert "DHS decides eligibility" in referrals["notice"]
    assert "may help" in referrals["notice"]
    assert referrals["official_url"] == "https://humanservices.hawaii.gov/bessd/snap/"
    assert referrals["fallback_url"] == "https://auw211.org/"
    assert {contact["service_area"] for contact in referrals["assistance"]} == {
        "State of Hawaiʻi",
        "Hawaiʻi Island",
        "Oʻahu",
        "Kauaʻi",
        "Maui",
    }
    for contact in referrals["assistance"]:
        assert contact["phone"] in (output / contact["evidence"]).read_text()
    rules = (output / "evidence/dhs-snap.html").read_text()
    assert "Effective 10/1/2026" in rules
    assert "200% FPL" in rules
    assert "not subject to the net income test" in rules
    outreach = (output / "evidence/dhs-outreach.html").read_text()
    assert "Federal Fiscal Year 2027" in outreach
    assert "October 1, 2026" in outreach


def test_offline_check_rejects_wrong_evidence_source(tmp_path: Path) -> None:
    import json

    from scripts.independent_snap import validate_artifacts

    output = tmp_path / "snap"
    shutil.copytree(ROOT / "data/snap", output)
    path = output / "evidence.json"
    manifest = json.loads(path.read_bytes())
    manifest["evidence/dhs-snap.html"]["source_url"] = "https://example.org/"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Evidence source URL mismatch"):
        validate_artifacts(output, GOLDEN)


def test_summary_replay_checks_actual_metadata(tmp_path: Path) -> None:
    import json

    from scripts.independent_snap import build_summary

    output = tmp_path / "snap"
    shutil.copytree(ROOT / "data/snap/evidence", output / "evidence")
    path = output / "evidence/census-metadata.json"
    metadata = json.loads(path.read_bytes())
    metadata["label"] = "Households receiving SNAP"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Summary metadata label mismatch"):
        build_summary(output, dry_run=False)
    assert not (output / "facts.db").exists()


def test_oracle_reports_missing_district(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import independent_snap as oracle

    responses = {
        oracle.METADATA_URL: (ROOT / "data/snap/evidence/census-metadata.json").read_bytes(),
        oracle.SUMMARY_URL: "|".join(oracle.HEADER).encode() + b"\n",
    }
    monkeypatch.setattr(oracle, "request", responses.__getitem__)
    with pytest.raises(ValueError, match="Independent summary missing House district 1"):
        oracle.fetch()


def test_oracle_contains_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import independent_snap as oracle

    def unavailable(url: str, timeout: int) -> None:
        raise OSError("untrusted upstream response")

    monkeypatch.setattr(oracle, "urlopen", unavailable)
    with pytest.raises(ValueError, match=r"^Independent Census request failed$"):
        oracle.request(oracle.SUMMARY_URL)


def test_check_runs_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import independent_snap as oracle

    def forbidden(url: str) -> bytes:
        pytest.fail("offline check attempted a fetch")

    monkeypatch.setattr(oracle, "request", forbidden)
    monkeypatch.setattr("sys.argv", ["independent_snap"])
    assert oracle.main() == 0


def test_check_missing_artifacts_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import independent_snap as oracle

    monkeypatch.setattr(oracle, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["independent_snap"])
    assert oracle.main() == 1
    assert "Missing SNAP artifacts" in capsys.readouterr().err


def test_preview_requires_build_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import independent_snap as oracle

    monkeypatch.setattr("sys.argv", ["independent_snap", "--dry-run"])
    with pytest.raises(SystemExit) as error:
        oracle.main()
    assert error.value.code == 2
