"""Isolated, reproducible SNAP outreach observations (WO163, step one of WO137)."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app.facts import FactStore
from etl.census import CensusError

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).parent / "fixtures/wo137_census.json"


def snapshot(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


@pytest.mark.parametrize("source", [SOURCE, ROOT / "data/outreach/facts/source.json"])
def test_independent_reproduction_and_offline_rebuild(tmp_path: Path, source: Path) -> None:
    from app.outreach_store import outreach_store
    from etl.outreach import build, check

    existing = snapshot(ROOT / "data")
    first, second = tmp_path / "first", tmp_path / "second"
    assert build(first, source=source) == 77
    assert build(second, source=first / "source.json") == 77
    assert snapshot(first) == snapshot(second)
    assert check(first)
    raw = json.loads(source.read_text())
    with sqlite3.connect(first / "facts.db") as db:
        rows = db.execute("SELECT geography, value, moe FROM facts").fetchall()
    expected: dict[str, tuple[float | None, ...]] = {}
    for request, batch in raw["batches"].items():
        for row in batch["rows"]:
            chamber = "house" if "lower" in request else "senate"
            key = "state:15" if request == "state:15" else f"{chamber}:15:{row[request[:-2]]}:2022"
            expected[key] = tuple(
                float(row[v]) if row[v] is not None and float(row[v]) >= 0 else None
                for v in ("B22003_006E", "B22003_006M")
            )
    assert {key: (value, moe) for key, value, moe in rows} == expected
    facts = FactStore(first / "facts.db").get(
        [("B22003_006E", key) for key in expected], "2020–2024"
    )
    assert len(facts) == 77
    assert all(f.table_id == "B22003" and f.source and f.method for f in facts.values())
    assert outreach_store().path == ROOT / "data/outreach/facts/facts.db"
    assert snapshot(ROOT / "data") == existing
    assert check(ROOT / "data/outreach/facts")


@pytest.mark.parametrize("failure", ["missing", "label", "endpoint", "vintage", "numeric"])
def test_failed_rebuild_preserves_artifacts(tmp_path: Path, failure: str) -> None:
    from etl.outreach import build

    output = tmp_path / "published"
    build(output, source=SOURCE)
    before = snapshot(output)
    raw = json.loads(SOURCE.read_text())
    state = raw["batches"]["state:15"]
    if failure == "missing":
        raw["batches"].pop(next(k for k in raw["batches"] if "lower" in k))
    elif failure == "label":
        state["labels"]["B22003_006E"] = "Wrong meaning"
    elif failure == "endpoint":
        state["endpoint"] = "https://example.org"
    elif failure == "vintage":
        state["vintage"] = "2019–2023"
    else:
        state["rows"][0]["B22003_006E"] = "NaN"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(raw))
    with pytest.raises(
        (ValueError, CensusError),
        match={
            "missing": "geography requests",
            "label": "metadata",
            "endpoint": "metadata",
            "vintage": "metadata",
            "numeric": "numeric Census cell",
        }[failure],
    ):
        build(output, source=source)
    assert snapshot(output) == before


def test_explicit_unavailability_and_provenance(tmp_path: Path) -> None:
    from etl.outreach import build, check

    raw = json.loads(SOURCE.read_text())
    raw["batches"]["state:15"]["rows"][0]["B22003_006E"] = "-666666666"
    source = tmp_path / "unavailable.json"
    source.write_text(json.dumps(raw))
    output = tmp_path / "published"
    build(output, source=source)
    fact = FactStore(output / "facts.db").get([("B22003_006E", "state:15")], "2020–2024")
    assert fact[("B22003_006E", "state:15")].reliability == "unavailable"
    provenance = json.loads((output / "provenance.json").read_text())
    assert (
        provenance["source_sha256"]
        == hashlib.sha256((output / "source.json").read_bytes()).hexdigest()
    )
    (output / "source.json").write_text("{}")
    with pytest.raises(ValueError, match="provenance"):
        check(output)


@pytest.mark.parametrize("damage", ["missing", "provenance", "value", "extra"])
def test_offline_check_rejects_damaged_publication(tmp_path: Path, damage: str) -> None:
    from etl.outreach import build, check

    build(tmp_path, source=SOURCE)
    if damage == "missing":
        (tmp_path / "facts.db").unlink()
    elif damage == "provenance":
        provenance = json.loads((tmp_path / "provenance.json").read_text())
        provenance["table_id"] = "wrong"
        (tmp_path / "provenance.json").write_text(json.dumps(provenance))
    else:
        with sqlite3.connect(tmp_path / "facts.db") as db:
            if damage == "value":
                db.execute("UPDATE facts SET value=value+1 WHERE geography='state:15'")
            else:
                db.execute(
                    "INSERT INTO facts SELECT variable, 'extra', vintage, value, moe, "
                    "cv, reliability, source, table_id, method, endpoint, label, "
                    "estimate_annotation, moe_annotation FROM facts WHERE geography='state:15'"
                )
        # Re-export independently so only the source reconciliation rejects this.
        with sqlite3.connect(tmp_path / "facts.db") as db:
            cursor = db.execute("SELECT * FROM facts ORDER BY variable, geography, vintage")
            lines = ["\t".join(c[0] for c in cursor.description)]
            lines.extend("\t".join("" if v is None else str(v) for v in row) for row in cursor)
        (tmp_path / "facts.tsv").write_text("\n".join(lines) + "\n")
        (tmp_path / "facts.sha256").write_text(
            "".join(
                f"{hashlib.sha256((tmp_path / n).read_bytes()).hexdigest()}  {n}\n"
                for n in ("facts.db", "facts.tsv")
            )
        )
    with pytest.raises(
        ValueError, match=r"Missing outreach facts|provenance differs|facts differ from source"
    ):
        check(tmp_path)


def test_live_fetch_failure_preserves_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etl.census import CensusClient
    from etl.outreach import build

    build(tmp_path, source=SOURCE)
    before = snapshot(tmp_path)

    from etl.census import CensusBatch
    from etl.indicators import Indicator
    from etl.outreach import Source

    batches = Source.model_validate_json(SOURCE.read_bytes()).batches

    def fail(client: CensusClient, indicator: Indicator, geography: str) -> CensusBatch:
        if "upper" in geography:
            raise CensusError("recorded fetch failure")
        return batches[geography]

    monkeypatch.setattr(CensusClient, "fetch", fail)
    with pytest.raises(CensusError, match="recorded fetch failure"):
        build(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["--check", "--dry-run", "build"])
def test_cli_offline_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    from etl.outreach import build, main

    if mode == "--check":
        build(tmp_path, source=SOURCE)
    before = snapshot(tmp_path)
    arguments = ["outreach", "--source", str(SOURCE), "--output", str(tmp_path)]
    monkeypatch.setattr("sys.argv", arguments + ([] if mode == "build" else [mode]))
    main()
    if mode == "build":
        assert (tmp_path / "facts.db").is_file()
    else:
        assert snapshot(tmp_path) == before
