"""WO158 / WO136 step 1: isolated SNAP builds preserve core facts and failures."""

import io
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from etl import build as writer
from etl.census import CensusClient, CensusError, load_config
from etl.indicators import Indicator

ROOT = Path(__file__).resolve().parents[2]
VARIABLE = "B22003_006E"
LABEL = (
    "Estimate!!Total:!!Household did not receive Food Stamps/SNAP in the past 12 months:"
    "!!Income in the past 12 months below poverty level"
)


@pytest.fixture
def snap_http(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Synthetic complete geography sets; exercise the real metadata and fact gates."""
    settings = {
        "label": LABEL,
        "attributes": "B22003_006EA,B22003_006M,B22003_006MA",
        "estimate": "100",
        "moe": "20",
    }

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout > 0
        parts = urlsplit(url)
        if parts.path.endswith(VARIABLE + ".json"):
            payload: object = {"label": settings["label"], "attributes": settings["attributes"]}
        else:
            query = parse_qs(parts.query)
            assert query["get"] == ["B22003_006E,B22003_006M,B22003_006EA,B22003_006MA"]
            column = query["for"][0].split(":")[0]
            codes = (
                ["15"]
                if column == "state"
                else ["001", "003", "005", "007", "009"]
                if column == "county"
                else [f"{i:03}" for i in range(1, 52 if "lower" in column else 26)]
            )
            header = [*query["get"][0].split(","), "state"]
            if column != "state":
                header.append(column)
            payload = [header] + [
                [settings["estimate"], settings["moe"], None, None, "15"]
                + ([] if column == "state" else [code])
                for code in codes
            ]
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("etl.census.urlopen", respond)
    return settings


def artifacts(path: Path) -> dict[str, bytes]:
    return {name: (path / name).read_bytes() for name in writer.ARTIFACTS}


def test_parameterized_writer_builds_selected_indicator(
    tmp_path: Path, snap_http: dict[str, str]
) -> None:
    config = load_config(ROOT / "config.toml")
    config.labels[VARIABLE] = LABEL
    client = CensusClient(config)
    assert writer.build(client, tmp_path, indicators=(Indicator((VARIABLE,), "detailed"),)) == 81
    assert writer.check(tmp_path)
    with sqlite3.connect(tmp_path / "facts.db") as db:
        assert db.execute("SELECT DISTINCT variable FROM facts").fetchall() == [(VARIABLE,)]


def test_snap_build_isolated_canonical_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snap_http: dict[str, str]
) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    core = tmp_path / "data"
    core.mkdir()
    for name in writer.ARTIFACTS:
        (core / name).write_bytes(b"existing core artifact")
    before = artifacts(core)
    config = load_config(ROOT / "config.toml")
    assert snap.build(config) == 81
    output = core / "snap"
    first = artifacts(output)
    assert snap.build(config) == 81
    assert artifacts(output) == first
    assert artifacts(core) == before
    assert VARIABLE not in config.labels
    assert writer.check(output)
    with sqlite3.connect(output / "facts.db") as db:
        rows = db.execute("SELECT variable, table_id, label, value, moe FROM facts").fetchall()
    assert rows == [(VARIABLE, "B22003", LABEL, 100, 20)] * 81


@pytest.mark.parametrize("cell", ["estimate", "moe"])
@pytest.mark.parametrize(
    "sentinel", ["-666666666", "-999999999", "-888888888", "-555555555", "-222222222", "-333333333"]
)
def test_snap_sentinels_are_never_figures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snap_http: dict[str, str],
    cell: str,
    sentinel: str,
) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    snap_http[cell] = sentinel
    snap.build(load_config(ROOT / "config.toml"))
    with sqlite3.connect(tmp_path / "data/snap/facts.db") as db:
        column = "value" if cell == "estimate" else "moe"
        rows = db.execute(f"SELECT {column}, cv, reliability, method FROM facts").fetchall()
    assert len(rows) == 81
    status = "controlled" if sentinel == "-555555555" else "not available"
    flag = "unavailable" if cell == "estimate" else "caution"
    assert all(row[:3] == (None, None, flag) and status in row[3] for row in rows)
    if sentinel == "-333333333":
        assert all("open-ended interval" in row[3] for row in rows)


@pytest.mark.parametrize(
    ("field", "bad", "error"),
    [
        ("label", "Receipt only", "Label mismatch"),
        ("attributes", "B22003_006EA,B22003_006MA", "Missing MOE"),
        ("estimate", "NaN", "Invalid numeric Census cell"),
    ],
)
def test_failed_snap_build_preserves_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snap_http: dict[str, str],
    field: str,
    bad: str,
    error: str,
) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    config = load_config(ROOT / "config.toml")
    snap.build(config)
    output = tmp_path / "data/snap"
    before = artifacts(output)
    snap_http[field] = bad
    with pytest.raises(CensusError, match=error):
        snap.build(config)
    assert artifacts(output) == before
    assert {p.name for p in output.iterdir()} == set(writer.ARTIFACTS)


@pytest.mark.parametrize("destination", ["data", "data/snap/../../escape", "elsewhere"])
def test_snap_rejects_output_outside_snap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="data/snap"):
        snap.build(load_config(ROOT / "config.toml"), tmp_path / destination)
    assert not list(tmp_path.iterdir())


def test_snap_rejects_symlink_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    (tmp_path / "data/snap").mkdir(parents=True)
    (tmp_path / "data/snap/link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="data/snap"):
        snap.build(load_config(ROOT / "config.toml"), tmp_path / "data/snap/link")


@pytest.mark.parametrize("mode", ["build", "--dry-run", "--check"])
def test_snap_cli_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snap_http: dict[str, str], mode: str
) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    output = tmp_path / "data/snap"
    if mode == "--check":
        snap.build(load_config(ROOT / "config.toml"))
    args = ["etl.snap", "--config", str(ROOT / "config.toml")]
    if mode != "build":
        args.append(mode)
    monkeypatch.setattr("sys.argv", args)
    assert snap.main() == 0
    if mode == "--dry-run":
        assert not output.exists()
    else:
        assert writer.check(output)


def test_snap_cli_reports_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etl import snap

    monkeypatch.setattr(snap, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["etl.snap", "--output", str(tmp_path)])
    assert snap.main() == 1
    assert not list(tmp_path.iterdir())


def test_snap_cli_rejects_conflicting_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    from etl import snap

    monkeypatch.setattr("sys.argv", ["etl.snap", "--check", "--dry-run"])
    with pytest.raises(SystemExit, match="2"):
        snap.main()
