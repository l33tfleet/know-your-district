"""WO145 step 1 (#198): named islands, reviewed district membership, optional coastlines.

Pins the work order's decisions: all 76 districts resolve to correctly named
islands; multi-island districts list every island they touch; each island states
coastline availability (unavailable has a reason and no geometry); malformed
inputs fail validation; the import replays offline byte-identically; existing
district files stay unchanged; counties are never substituted for islands.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.boundaries import all_districts
from etl.islands import ISLANDS, build_islands, load_islands

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "data/geo"
COMMITTED = GEO / "islands"
FIXTURES = Path(__file__).resolve().parent / "fixtures/wo145_islands"
NAMES = {
    "hawaii": "Hawaiʻi Island",
    "maui": "Maui",
    "kahoolawe": "Kahoʻolawe",
    "lanai": "Lānaʻi",
    "molokai": "Molokaʻi",
    "oahu": "Oʻahu",
    "kauai": "Kauaʻi",
    "niihau": "Niʻihau",
}
DISTRICT_FILES = [
    f"{chamber}{suffix}"
    for chamber in ("house", "senate")
    for suffix in (".geojson", ".provenance.json", ".credit.txt")
]


def digests(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def geo_copy(tmp_path: Path) -> Path:
    geo = tmp_path / "geo"
    geo.mkdir()
    for name in DISTRICT_FILES:
        shutil.copyfile(GEO / name, geo / name)
    return geo


def test_island_names_use_okina_and_kahako() -> None:
    assert ISLANDS == NAMES
    for name in NAMES.values():
        assert "'" not in name and chr(0x2018) not in name


def test_all_76_districts_resolve_to_named_islands() -> None:
    data = load_islands(COMMITTED)
    assert {island.id: island.name for island in data.islands} == NAMES
    expected = {d.key for chamber in ("house", "senate") for d in all_districts(chamber)}
    assert set(data.membership) == expected
    assert len(data.membership) == 76
    for islands in data.membership.values():
        assert islands and set(islands) <= set(NAMES)


def test_multi_island_districts_list_every_island() -> None:
    membership = load_islands(COMMITTED).membership
    maui_nui = ["maui", "kahoolawe", "lanai", "molokai"]
    assert membership["house-13"] == maui_nui
    assert membership["senate-07"] == maui_nui
    assert membership["house-17"] == ["kauai", "niihau"]
    assert membership["senate-08"] == ["kauai", "niihau"]
    assert membership["house-01"] == ["hawaii"]
    assert membership["house-14"] == ["maui"]
    assert membership["senate-25"] == ["oahu"]
    every = {island for islands in membership.values() for island in islands}
    assert every == set(NAMES)


def test_committed_islands_record_coastline_state_and_provenance() -> None:
    data = load_islands(COMMITTED)
    for island in data.islands:
        if island.coastline.status == "unavailable":
            assert len(island.coastline.reason) > 20
            assert island.id not in data.coastlines
        else:
            assert island.id in data.coastlines
    provenance = json.loads((COMMITTED / "islands.json").read_text(encoding="utf-8"))["provenance"]
    sources = provenance["district_sources"]
    assert [source["chamber"] for source in sources] == ["house", "senate"]
    for source in sources:
        assert source["source_url"].startswith("https://geodata.hawaii.gov/")
    assert "No county polygons" in provenance["membership_method"]
    assert "Board on Geographic Names" in provenance["name_authority"]
    assert (COMMITTED / "credit.txt").read_text(encoding="utf-8").strip()


def test_offline_replay_is_byte_identical_and_leaves_districts_unchanged(
    tmp_path: Path,
) -> None:
    before = digests(GEO)
    output = tmp_path / "islands"
    build_islands(GEO, output)
    assert digests(output) == digests(COMMITTED)
    assert digests(GEO) == before
    build_islands(GEO, output)
    assert digests(output) == digests(COMMITTED)


def test_verified_coastline_replay_records_provenance(tmp_path: Path) -> None:
    output = tmp_path / "islands"
    build_islands(GEO, output, FIXTURES)
    data = load_islands(output)
    states = {island.id: island.coastline for island in data.islands}
    assert {i for i, c in states.items() if c.status == "available"} == {"oahu", "maui"}
    assert set(data.coastlines) == {"oahu", "maui"}
    oahu = states["oahu"]
    assert oahu.status == "available"
    assert str(oahu.source.service_url).startswith("https://geodata.hawaii.gov/")
    assert oahu.source.layer_id == 7
    assert oahu.source.retrieved_on.isoformat() == "2026-10-29"
    assert "Statewide GIS" in oahu.source.credit
    for island_id, state in states.items():
        if state.status == "unavailable":
            assert state.reason and island_id not in data.coastlines
    # The Northwestern Hawaiian Islands square is outside every island and dropped.
    for x, y in data.coastlines["maui"].coordinates[0][0]:
        assert -157 < x < -156 and 20 < y < 21
    assert "Fixture credit" in (output / "credit.txt").read_text(encoding="utf-8")
    first = digests(output)
    build_islands(GEO, output, FIXTURES)
    assert digests(output) == first


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("islands.json", '"Lānaʻi"', '"Lana\'i"'),
        ("islands.json", '"id": "niihau"', '"id": "nihoa"'),
        ("islands.json", '"status": "unavailable"', '"status": "missing"'),
        ("membership.json", '"house-01": ["hawaii"]', '"house-01": []'),
        ("membership.json", '"house-01": ["hawaii"]', '"house-01": ["honolulu"]'),
        ("membership.json", '"house-13": ["maui", "kahoolawe", "lanai"', '"house-13": ["maui"'),
        ("membership.json", '"house-51"', '"house-52"'),
    ],
)
def test_malformed_island_files_fail_validation(
    tmp_path: Path, name: str, old: str, new: str
) -> None:
    directory = tmp_path / "islands"
    shutil.copytree(COMMITTED, directory)
    rewrite(directory / name, old, new)
    with pytest.raises((ValueError, ValidationError)):
        load_islands(directory)


def test_unavailable_coastline_needs_reason_and_no_geometry(tmp_path: Path) -> None:
    directory = tmp_path / "islands"
    build_islands(GEO, directory, FIXTURES)
    document = json.loads((directory / "islands.json").read_text(encoding="utf-8"))
    for island in document["islands"]:
        if island["coastline"]["status"] == "unavailable":
            island["coastline"]["reason"] = ""
    (directory / "islands.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_islands(directory)
    shutil.rmtree(directory)
    build_islands(GEO, directory, FIXTURES)
    document = json.loads((directory / "islands.json").read_text(encoding="utf-8"))
    for island in document["islands"]:
        if island["id"] == "oahu":
            island["coastline"] = {"status": "unavailable", "reason": "x" * 30}
    (directory / "islands.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="oahu"):
        load_islands(directory)
    (directory / "coastlines.geojson").unlink()
    build_islands(GEO, directory, FIXTURES)
    (directory / "coastlines.geojson").unlink()
    with pytest.raises((OSError, ValueError)):
        load_islands(directory)


def test_district_part_outside_every_island_fails(tmp_path: Path) -> None:
    geo = geo_copy(tmp_path)
    document = json.loads((geo / "house.geojson").read_text(encoding="utf-8"))
    document["features"][0]["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[-150.0, 10.0], [-149.9, 10.0], [-149.9, 10.1], [-150.0, 10.0]]],
    }
    (geo / "house.geojson").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="house-01"):
        build_islands(geo, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_membership_must_match_reviewed_list(tmp_path: Path) -> None:
    geo = geo_copy(tmp_path)
    document = json.loads((geo / "senate.geojson").read_text(encoding="utf-8"))
    feature = next(f for f in document["features"] if f["properties"]["district"] == 8)
    feature["geometry"]["coordinates"] = feature["geometry"]["coordinates"][:1]
    (geo / "senate.geojson").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="senate-08"):
        build_islands(geo, tmp_path / "out")


@pytest.mark.parametrize(
    "change",
    [
        {"layer_id": None},
        {"retrieved_on": "29/10/2026"},
        {"credit": ""},
        {"service_url": "http://example.com/coast"},
    ],
)
def test_malformed_coastline_source_fails(tmp_path: Path, change: dict[str, object]) -> None:
    source = tmp_path / "coast"
    shutil.copytree(FIXTURES, source)
    meta = json.loads((source / "coastline.source.json").read_text(encoding="utf-8"))
    (source / "coastline.source.json").write_text(json.dumps(meta | change), encoding="utf-8")
    with pytest.raises((ValueError, ValidationError)):
        build_islands(GEO, tmp_path / "out", source)


def test_incomplete_coastline_response_fails(tmp_path: Path) -> None:
    source = tmp_path / "coast"
    shutil.copytree(FIXTURES, source)
    payload = json.loads((source / "coastline.geojson").read_text(encoding="utf-8"))
    payload["exceededTransferLimit"] = True
    (source / "coastline.geojson").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="exceededTransferLimit"):
        build_islands(GEO, tmp_path / "out", source)
