"""WO145 step 1 (#198): named islands, reviewed district membership, optional coastlines."""

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from etl.boundaries import all_districts
from etl.islands import ISLANDS, NOT_RETRIEVED, IslandsDocument, build_islands, main, plan_islands
from etl.islands import preview as preview_line

GEO = Path(__file__).resolve().parents[2] / "data/geo"
COMMITTED = GEO / "islands"
FIXTURES = Path(__file__).resolve().parent / "fixtures/wo145_islands"
Capsys = pytest.CaptureFixture[str]
Patch = pytest.MonkeyPatch
NAMES = ["Hawaiʻi Island", "Maui", "Kahoʻolawe", "Lānaʻi", "Molokaʻi", "Oʻahu", "Kauaʻi", "Niʻihau"]


def digests(directory: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob("*.*")}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_islands_are_named_with_okina_and_kahako() -> None:
    assert [name for name, _ in ISLANDS.values()] == NAMES
    document = IslandsDocument.model_validate(load(COMMITTED / "islands.json"))
    assert [island.name for island in document.islands] == NAMES


def test_all_76_districts_list_every_island_they_touch() -> None:
    membership = load(COMMITTED / "membership.json")
    expected = {d.key for chamber in ("house", "senate") for d in all_districts(chamber)}
    assert set(membership) == expected and len(membership) == 76
    maui_nui = ["maui", "kahoolawe", "lanai", "molokai"]
    assert membership["house-13"] == membership["senate-07"] == maui_nui
    assert membership["house-17"] == membership["senate-08"] == ["kauai", "niihau"]
    assert membership["house-01"] == ["hawaii"] and membership["senate-25"] == ["oahu"]
    assert {i for islands in membership.values() for i in islands} == set(ISLANDS)


def test_committed_coastlines_are_unavailable_with_reason_and_provenance() -> None:
    document = IslandsDocument.model_validate(load(COMMITTED / "islands.json"))
    assert {i.coastline.model_dump().get("reason") for i in document.islands} == {NOT_RETRIEVED}
    assert not (COMMITTED / "coastlines.geojson").exists()
    sources = document.provenance.district_sources
    assert len(sources) == 2
    assert all(str(s.source_url).startswith("https://geodata.hawaii.gov/") for s in sources)
    assert "No county polygons" in document.provenance.membership_method
    assert "Office of Elections" in (COMMITTED / "credit.txt").read_text(encoding="utf-8")


def test_offline_replay_is_byte_identical_and_leaves_districts_unchanged(tmp_path: Path) -> None:
    before = digests(GEO)
    build_islands(GEO, tmp_path)
    assert digests(tmp_path) == digests(COMMITTED)
    assert digests(GEO) == before


def test_verified_coastline_replay_records_source_and_drops_outlying_parts(tmp_path: Path) -> None:
    build_islands(GEO, tmp_path, FIXTURES)
    first = digests(tmp_path)
    document = IslandsDocument.model_validate(load(tmp_path / "islands.json"))
    states = {island.id: island.coastline.model_dump(mode="json") for island in document.islands}
    source = load(FIXTURES / "coastline.source.json")
    assert {i for i, s in states.items() if s["status"] == "available"} == {"oahu", "maui"}
    assert states["oahu"]["source"] == states["maui"]["source"] == source
    assert len(states["kauai"]["reason"]) >= 20 and "source" not in states["kauai"]
    features = load(tmp_path / "coastlines.geojson")["features"]
    assert [f["properties"]["island"] for f in features] == ["maui", "oahu"]
    assert len(features[0]["geometry"]["coordinates"]) == 1  # the outlying square is dropped
    assert source["credit"] in (tmp_path / "credit.txt").read_text(encoding="utf-8")
    build_islands(GEO, tmp_path, FIXTURES)
    assert digests(tmp_path) == first


def square(west: float, south: float, size: float = 0.1) -> dict[str, object]:
    ring = [[west, south], [west + size, south], [west + size, south + size], [west, south]]
    return {"type": "Polygon", "coordinates": [ring]}


ISLAND_ROWS = load(COMMITTED / "islands.json")["islands"]
SOURCE, LAYER, COAST = "coastline.source.json", "coastline.geojson", ("islands", 0, "coastline")
# (file, path to the changed value, new value, the specific error). islands.json cases check
# the document contract; every other file is an import input and must fail before writing.
CASES: list[tuple[str, tuple[str | int, ...], object, str]] = [
    ("islands.json", ("islands", 3, "name"), "Lana'i", "lanai must be named 'Lānaʻi'"),
    ("islands.json", ("islands",), ISLAND_ROWS[:7], "islands must be exactly"),
    ("islands.json", ("islands",), ISLAND_ROWS + ISLAND_ROWS[:1], "islands must be exactly"),
    ("islands.json", ("islands", 7, "id"), "nihoa", r"islands\.7\.id\n  Input should be"),
    ("islands.json", (*COAST, "reason"), "x", "reason\n  String should have at least 20"),
    ("islands.json", (*COAST, "geometry"), {}, "geometry\n  Extra inputs are not permitted"),
    ("islands.json", (*COAST, "status"), "gone", "does not match any of the expected tags"),
    ("islands.json", COAST, {"status": "available"}, r"available\.source\n  Field required"),
    ("islands.json", ("provenance", "note"), "x", "note\n  Extra inputs are not permitted"),
    ("islands.json", ("provenance", "district_sources"), "x", "district_sources\n  Input should"),
    ("islands.json", ("provenance", "district_sources"), [], "district_sources\n  List should"),
    (SOURCE, ("service_url",), "http://geodata.hawaii.gov/x", "service_url\n  String should"),
    (SOURCE, ("service_url",), "https://example.com/x", "service_url\n  String should match"),
    (SOURCE, ("layer_id",), None, "layer_id\n  Input should be a valid integer"),
    (SOURCE, ("layer_id",), -1, "layer_id\n  Input should be greater than or equal to 0"),
    (SOURCE, ("layer_id",), "12", "layer_id\n  Input should be a valid integer"),
    (SOURCE, ("retrieved_on",), "29/10/2026", "retrieved_on must be an ISO"),
    (SOURCE, ("retrieved_on",), 1761700000, "retrieved_on must be an ISO"),
    (SOURCE, ("credit",), "", "credit\n  String should have at least 1 character"),
    (SOURCE, ("credit",), "a\nb", "credit\n  String should match"),
    (SOURCE, ("note",), "x", "note\n  Extra inputs are not permitted"),
    (LAYER, ("features",), {}, "features\n  Input should be a valid array"),
    (LAYER, ("features",), [], "no polygon in any island extent"),
    (LAYER, ("features", 0, "geometry", "coordinates"), "x", "coordinates\n  Input should be"),
    (LAYER, ("exceededTransferLimit",), "no", "exceededTransferLimit\n  Input should be a valid"),
    (LAYER, ("exceededTransferLimit",), True, "incomplete response: exceededTransferLimit"),
    (LAYER, ("properties",), {"exceededTransferLimit": True}, "incomplete response"),
    (LAYER, ("features", 0, "geometry"), square(-157.65, 21.3), "not within exactly one island"),
    ("house.geojson", ("features", 0, "properties", "district"), None, r"district\.int\n  Input"),
    ("house.geojson", ("features", 0, "geometry"), square(-150, 10), "house-01: part .* not"),
    ("senate.geojson", ("features", 7, "geometry"), square(-159.6, 22.0), r"\['senate-08'\]"),
]


@pytest.mark.parametrize(("name", "path", "value", "error"), CASES)
def test_each_malformed_input_fails_its_own_validation(
    tmp_path: Path, name: str, path: tuple[str | int, ...], value: object, error: str
) -> None:
    geo = shutil.copytree(GEO, tmp_path / "geo")
    coast = shutil.copytree(FIXTURES, tmp_path / "coast")
    target = {"islands.json": geo / "islands", SOURCE: coast, LAYER: coast}.get(name, geo) / name
    document = load(target)
    parent: Any = document
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValueError, match=error):
        if name == "islands.json":
            IslandsDocument.model_validate(document)
        target.write_text(json.dumps(document), encoding="utf-8")
        build_islands(geo, tmp_path / "out", coast)
    assert not (tmp_path / "out").exists()


def test_preview_shows_the_planned_actions_and_writes_nothing(
    tmp_path: Path, capsys: Capsys, monkeypatch: Patch
) -> None:
    (tmp_path / "coastlines.geojson").write_text("stale", encoding="utf-8")
    before = digests(tmp_path)
    actions = plan_islands(GEO, tmp_path)
    assert [a.path.name for a in actions[:3]] == ["islands.json", "membership.json", "credit.txt"]
    assert actions[3].path.name == "coastlines.geojson" and actions[3].text is None
    assert len(plan_islands(GEO, tmp_path / "new")) == 3  # nothing stale, nothing to remove
    monkeypatch.setattr("sys.argv", ["islands", "--output-dir", str(tmp_path), "--dry-run"])
    main()
    lines = capsys.readouterr().out.splitlines()
    assert lines == [preview_line(action) for action in actions]
    assert digests(COMMITTED)["islands.json"] in lines[0] and lines[3].startswith("remove ")
    assert digests(tmp_path) == before
    monkeypatch.setattr("sys.argv", ["islands", "--output-dir", str(tmp_path)])
    main()
    assert digests(tmp_path) == digests(COMMITTED)  # the same actions remove the stale file


@pytest.mark.parametrize(
    ("args", "code", "error"),
    [
        (["--geo-dir", "{tmp}/missing"], 1, r"Island build failed: .*house\.provenance\.json"),
        (["--geo-dir", "{tmp}/broken"], 1, "Island build failed: .*Invalid JSON"),
        (["--geo-dir", "{tmp}/array"], 1, "Island build failed: .*Input should be an object"),
        (["--coastline-dir", "{tmp}/missing"], 1, r"failed: .*coastline\.source\.json"),
        (["--output-dir", "{tmp}/file"], 1, "Island build failed: .*file"),
        (["--bogus"], 2, "unrecognized arguments: --bogus"),
    ],
)
def test_each_command_failure_exits_nonzero_with_its_own_message(
    tmp_path: Path, capsys: Capsys, monkeypatch: Patch, args: list[str], code: int, error: str
) -> None:
    (tmp_path / "file").write_text("", encoding="utf-8")
    for name, text in (("broken", "{"), ("array", "[]")):
        geo = shutil.copytree(GEO, tmp_path / name)
        (geo / "house.provenance.json").write_text(text, encoding="utf-8")
    argv = [arg.format(tmp=tmp_path) for arg in args]
    monkeypatch.setattr("sys.argv", ["islands", "--output-dir", str(tmp_path / "out"), *argv])
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == code
    assert re.search(error, capsys.readouterr().err, re.DOTALL)
    assert not (tmp_path / "out").exists()
