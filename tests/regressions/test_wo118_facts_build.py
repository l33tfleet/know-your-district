"""WO118: reproducible offline fact builds and committed-artifact consistency."""

import hashlib
import io
import json
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.models import Fact
from etl.census import ACSConfig, CensusBatch, CensusClient, CensusError, load_config
from etl.indicators import Indicator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "data/schema.sql"
ARTIFACTS = ("facts.db", "facts.tsv", "facts.sha256")


@pytest.fixture
def recorded_client(monkeypatch: pytest.MonkeyPatch) -> CensusClient:
    """Replay fixed synthetic Census HTTP recordings, including metadata, without a key."""
    recordings = json.loads(
        (Path(__file__).parent / "fixtures/wo118_census.json").read_text(encoding="utf-8")
    )

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout > 0
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        assert "key" not in query
        key = parts.path
        if "get" in query:
            key += "|" + query["get"][0] + "|" + query["for"][0]
        assert key in recordings, f"Unrecorded request: {key}"
        return io.BytesIO(json.dumps(recordings[key]).encode("utf-8"))

    monkeypatch.setattr("etl.census.urlopen", respond)
    return CensusClient(load_config(ROOT / "config.toml"))


def snapshot(output: Path) -> dict[str, bytes]:
    return {name: (output / name).read_bytes() for name in ARTIFACTS}


def test_facts_build_exact_rows_and_canonical_bytes(
    tmp_path: Path, recorded_client: CensusClient
) -> None:
    from etl.build import build, check

    first, second = tmp_path / "first", tmp_path / "second"
    build(recorded_client, first)
    build(recorded_client, second)
    assert snapshot(first) == snapshot(second)
    assert {p.name for p in first.iterdir()} == set(ARTIFACTS)
    assert check(first)
    with sqlite3.connect(first / "facts.db") as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM facts ORDER BY variable, geography, vintage").fetchall()
        columns = [r[1] for r in db.execute("PRAGMA table_info(facts)")]
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert len(rows) == 243
    facts = [Fact.model_validate(dict(row)) for row in rows]
    assert {f.variable for f in facts} == {"B01003_001E", "DP05_0024PE", "B19013_001E"}
    expected_geographies = {"state:15", *(f"county:15:{c}" for c in ("001", "003", "007", "009"))}
    expected_geographies |= {f"house:15:{i:03}:2022" for i in range(1, 52)}
    expected_geographies |= {f"senate:15:{i:03}:2022" for i in range(1, 26)}
    assert {f.geography for f in facts} == expected_geographies
    assert all(f.vintage == "2020–2024" for f in facts)

    def cell(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return repr(value)
        return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")

    expected = "\t".join(columns) + "\n"
    expected += "".join("\t".join(cell(v) for v in row) + "\n" for row in rows)
    assert (first / "facts.tsv").read_bytes() == expected.encode("utf-8")
    assert (
        b"\\t" in expected.encode() and b"\\n" in expected.encode() and b"\\\\" in expected.encode()
    )
    assert any(f.value is None for f in facts)
    assert any("Hawaiʻi" in (f.estimate_annotation or "") for f in facts)
    hashes = "".join(
        f"{hashlib.sha256((first / name).read_bytes()).hexdigest()}  {name}\n"
        for name in ARTIFACTS[:2]
    )
    assert (first / "facts.sha256").read_bytes() == hashes.encode("utf-8")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE facts SET value = value + 1 WHERE geography = 'state:15'",
        "UPDATE facts SET source = 'Changed citation' WHERE geography = 'state:15'",
        "DELETE FROM facts WHERE geography = 'state:15'",
    ],
)
def test_facts_build_detects_database_drift(
    tmp_path: Path, recorded_client: CensusClient, sql: str
) -> None:
    from etl.build import build, check

    build(recorded_client, tmp_path)
    with sqlite3.connect(tmp_path / "facts.db") as db:
        db.execute(sql)
    with pytest.raises(ValueError):
        check(tmp_path)


@pytest.mark.parametrize("name", ["facts.tsv", "facts.sha256"])
def test_facts_build_detects_export_or_digest_drift(
    tmp_path: Path, recorded_client: CensusClient, name: str
) -> None:
    from etl.build import build, check

    build(recorded_client, tmp_path)
    (tmp_path / name).write_bytes((tmp_path / name).read_bytes() + b"changed\n")
    with pytest.raises(ValueError):
        check(tmp_path)


def test_facts_build_schema_change_requires_rebuild(
    tmp_path: Path, recorded_client: CensusClient
) -> None:
    from etl.build import build, check

    build(recorded_client, tmp_path)
    schema = tmp_path / "changed.sql"
    schema.write_text(SCHEMA.read_text().replace("value >= 0", "value >= 1"))
    with pytest.raises(ValueError, match="schema"):
        check(tmp_path, schema=schema)


@pytest.mark.parametrize("failure", ["census", "schema"])
def test_facts_build_failure_preserves_all_previous_artifacts(
    tmp_path: Path, recorded_client: CensusClient, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from etl.build import build

    build(recorded_client, tmp_path)
    before = snapshot(tmp_path)
    schema = SCHEMA
    if failure == "census":
        original = recorded_client.fetch
        calls = 0

        def fail_later(indicator: Indicator, geography: str) -> CensusBatch:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise CensusError("recorded Census failure")
            return original(indicator, geography)

        monkeypatch.setattr(recorded_client, "fetch", fail_later)
    else:
        schema = tmp_path.parent / "reject.sql"
        schema.write_text(SCHEMA.read_text().replace("value >= 0", "value >= 1e20"))
    with pytest.raises((CensusError, sqlite3.IntegrityError)):
        build(recorded_client, tmp_path, schema=schema)
    assert snapshot(tmp_path) == before
    assert {p.name for p in tmp_path.iterdir()} == set(ARTIFACTS)


def test_facts_build_absence_skips_with_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.build import check

    assert check(tmp_path) is False
    assert "no data yet: the data work order builds it" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_facts_build_cli_offline(
    tmp_path: Path, recorded_client: CensusClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etl import build as module

    def client_factory(config: ACSConfig, *, api_key: str | None = None) -> CensusClient:
        return recorded_client

    monkeypatch.setattr(module, "CensusClient", client_factory)
    monkeypatch.setattr("sys.argv", ["etl.build", "--dry-run", "--output", str(tmp_path)])
    assert module.main() == 0
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr("sys.argv", ["etl.build", "--output", str(tmp_path)])
    assert module.main() == 0
    monkeypatch.setattr("sys.argv", ["etl.build", "--check", "--output", str(tmp_path)])
    assert module.main() == 0
    (tmp_path / "facts.tsv").write_text("corrupt")
    assert module.main() == 1


def test_facts_build_make_targets() -> None:
    for target, command in (
        ("data", "python -m etl.build"),
        ("check", "python -m etl.build --check"),
    ):
        result = subprocess.run(
            ["make", "-n", target], cwd=ROOT, check=True, capture_output=True, text=True
        )
        assert command in result.stdout
