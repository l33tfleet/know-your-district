"""WO145 step 2 (#199): geometry, island names and attribution by qualified district ID."""

import hashlib
import json
import os
import re
import shutil
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.boundary_store import load_boundaries
from etl.boundaries import all_districts, expected_fact_keys
from etl.islands import ISLANDS, NOT_RETRIEVED, build_islands

GEO = Path(__file__).resolve().parents[2] / "data/geo"
FIXTURES = Path(__file__).resolve().parent / "fixtures/wo145_islands"
Edit = Callable[[Any], object]
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
WRITE_EVENTS = {"os.mkdir", "os.remove", "os.rename", "os.rmdir", "shutil.copyfile"}
audit_log: list[str] | None = None


def audit(event: str, args: tuple[Any, ...]) -> None:
    if audit_log is None:
        return
    writing = event == "open" and isinstance(args[2], int) and args[2] & WRITE_FLAGS
    if writing or event in WRITE_EVENTS or event.startswith("socket."):
        audit_log.append(f"{event} {args!r}")


sys.addaudithook(audit)  # audit hooks cannot be removed; audit_log is None outside the test


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digests(directory: Path) -> dict[str, str]:
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }


def copy_geo(tmp_path: Path) -> Path:
    return shutil.copytree(GEO, tmp_path / "geo")


def edit_json(path: Path, change: Edit) -> None:
    document = load(path)
    change(document)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def test_every_house_and_senate_id_resolves_to_geometry_islands_and_attribution() -> None:
    store = load_boundaries()
    assert set(store.districts) == expected_fact_keys() and len(store.districts) == 76
    membership = load(GEO / "islands/membership.json")
    for chamber in ("house", "senate"):
        features = {f["id"]: f for f in load(GEO / f"{chamber}.geojson")["features"]}
        credit = (GEO / f"{chamber}.credit.txt").read_text(encoding="utf-8").strip()
        source = load(GEO / f"{chamber}.provenance.json")["source_url"]
        for district in all_districts(chamber):
            entry = store.district(district.fact_key)
            assert entry.id == district.fact_key and entry.district == district
            assert [island.id for island in entry.islands] == membership[district.key]
            assert entry.attribution.credit == credit
            assert str(entry.attribution.provenance.source_url) == source
            assert "Board on Geographic Names" in entry.attribution.name_authority
            assert "No county polygons" in entry.attribution.membership_method
            raw = features[district.fact_key]["geometry"]
            assert json.loads(entry.geometry.model_dump_json()) == raw


def test_multi_island_districts_carry_every_island_name_with_okina_and_kahako() -> None:
    store = load_boundaries()
    names = ["Maui", "Kahoʻolawe", "Lānaʻi", "Molokaʻi"]
    house_13 = store.district("house:15:013:2022")
    assert [island.name for island in house_13.islands] == names
    senate_8 = store.district("senate:15:008:2022")
    assert [island.name for island in senate_8.islands] == ["Kauaʻi", "Niʻihau"]


@pytest.mark.parametrize(
    "reference",
    ["house-01", "house:15:052:2022", "senate:15:026:2022", "state:15", "", "../house.geojson"],
)
def test_an_unknown_reference_fails_loudly_naming_the_valid_form(reference: str) -> None:
    with pytest.raises(ValueError, match=r"unknown district id .* house:15:001:2022"):
        load_boundaries().district(reference)


def test_unavailable_coastlines_stay_explicit_for_the_silhouette_fallback() -> None:
    islands = load_boundaries().district("house:15:017:2022").islands
    for island in islands:
        assert island.geometry is None
        assert island.coastline.model_dump() == {"status": "unavailable", "reason": NOT_RETRIEVED}


def test_available_coastlines_keep_their_geometry_and_source(tmp_path: Path) -> None:
    geo = copy_geo(tmp_path)
    build_islands(geo, geo / "islands", FIXTURES)
    store = load_boundaries(geo)
    source = load(FIXTURES / "coastline.source.json")
    raw = {
        f["properties"]["island"]: f["geometry"]
        for f in load(geo / "islands/coastlines.geojson")["features"]
    }
    oahu = store.district("house:15:022:2022").islands[0]
    assert oahu.geometry is not None
    assert json.loads(oahu.geometry.model_dump_json()) == raw["oahu"]
    assert oahu.coastline.model_dump(mode="json") == {"status": "available", "source": source}
    kauai = store.district("senate:15:008:2022").islands[0]
    assert kauai.geometry is None and kauai.coastline.status == "unavailable"


def test_invalid_topology_is_exposed_as_exported_without_repair(tmp_path: Path) -> None:
    geo = copy_geo(tmp_path)
    bowtie = [[[-157.9, 21.3], [-157.8, 21.4], [-157.8, 21.3], [-157.9, 21.4], [-157.9, 21.3]]]
    shape = {"type": "Polygon", "coordinates": bowtie}
    edit_json(geo / "house.geojson", lambda d: d["features"][21].update(geometry=shape))
    assert (
        json.loads(load_boundaries(geo).district("house:15:022:2022").geometry.model_dump_json())
        == shape
    )


def test_loading_performs_no_writes_or_network_requests(tmp_path: Path) -> None:
    global audit_log
    geo = copy_geo(tmp_path)
    build_islands(geo, geo / "islands", FIXTURES)
    before = digests(geo)
    probe: list[str] = []
    audit_log = probe
    (tmp_path / "probe").write_text("", encoding="utf-8")
    socket.socket().close()
    assert len(probe) >= 2  # the audit really observes writes and sockets
    probe.clear()
    try:
        load_boundaries()
        load_boundaries(geo)
    finally:
        audit_log = None
    assert probe == []
    assert digests(geo) == before


def drop_first(document: Any) -> None:
    del document["features"][0]


def repeat_first(document: Any) -> None:
    document["features"].append(document["features"][0])


def senate_in_house(document: Any) -> None:
    document["features"][0].update(id="senate:15:001:2022")
    document["features"][0]["properties"] = {"chamber": "senate", "district": 1}


def house_key_on_senate_props(document: Any) -> None:
    document["features"][0]["properties"]["chamber"] = "senate"


def set_key(*path: str | int, value: object) -> Edit:
    def change(document: Any) -> None:
        for key in path[:-1]:
            document = document[key]
        document[path[-1]] = value

    return change


def remove_key(*path: str | int) -> Edit:
    def change(document: Any) -> None:
        for key in path[:-1]:
            document = document[key]
        del document[path[-1]]

    return change


FIRST_ISLAND = ("islands", 0)
# (file under data/geo, JSON edit, the specific error; every error names the file or the reference).
JSON_CASES: list[tuple[str, Edit, str]] = [
    ("house.geojson", drop_first, r"house\.geojson.*missing.*house:15:001:2022"),
    ("senate.geojson", drop_first, r"senate\.geojson.*missing.*senate:15:001:2022"),
    ("house.geojson", repeat_first, r"house\.geojson.*duplicate.*house:15:001:2022"),
    ("house.geojson", senate_in_house, r"house\.geojson.*senate:15:001:2022"),
    ("house.geojson", house_key_on_senate_props, r"house:15:001:2022.*does not match senate"),
    ("house.geojson", set_key("features", 0, "id", value="house:15:002:2022"), "does not match"),
    ("house.geojson", set_key("features", 0, "id", value="house-01"), "does not match"),
    ("senate.geojson", remove_key("features", 0, "id"), r"senate\.geojson.*id\n  Field required"),
    ("house.geojson", set_key("features", 0, "properties", "name", value="x"), "Extra inputs"),
    ("house.geojson", set_key("features", 0, "properties", "district", value=52), r"1\.\.51"),
    ("house.geojson", remove_key("features", 0, "geometry"), "geometry\n  Field required"),
    ("house.geojson", set_key("features", 0, "geometry", "coordinates", value="x"), "coordinates"),
    ("house.geojson", set_key("features", value={}), "features\n  Input should be"),
    ("house.provenance.json", remove_key("vintage"), r"house\.provenance\.json.*vintage"),
    ("senate.provenance.json", set_key("method", value="other"), "do not match islands.json"),
    ("house.provenance.json", set_key("plan_year", value=2012), "plan_year"),
    ("islands/islands.json", set_key(*FIRST_ISLAND, "name", value="Hawaii"), "must be named"),
    ("islands/islands.json", remove_key("islands", 3), "islands must be exactly"),
    ("islands/islands.json", set_key("islands", 7, "id", value="nihoa"), "Input should be"),
    ("islands/islands.json", remove_key(*FIRST_ISLAND, "coastline"), "coastline\n  Field required"),
    ("islands/membership.json", remove_key("house-01"), r"missing.*house-01"),
    ("islands/membership.json", remove_key("senate-25"), r"missing.*senate-25"),
    ("islands/membership.json", set_key("house-52", value=["oahu"]), r"unexpected.*house-52"),
    ("islands/membership.json", set_key("house-1", value=["hawaii"]), r"unexpected.*house-1\b"),
    ("islands/membership.json", set_key("house-01", value=["nihoa"]), "Input should be"),
    ("islands/membership.json", set_key("house-01", value=["maui"]), r"mismatched.*house-01"),
    ("islands/membership.json", set_key("house-01", value=[]), r"mismatched.*house-01"),
    ("islands/membership.json", set_key("house-17", value=["kauai"]), r"mismatched.*house-17"),
    ("islands/membership.json", set_key("house-17", value=["kauai", "kauai"]), "mismatched"),
    ("islands/membership.json", set_key("house-17", value="kauai"), "Input should be"),
]


@pytest.mark.parametrize(("name", "change", "error"), JSON_CASES)
def test_each_bad_artifact_is_rejected(tmp_path: Path, name: str, change: Edit, error: str) -> None:
    geo = copy_geo(tmp_path)
    edit_json(geo / name, change)
    with pytest.raises(ValueError, match=re.compile(error, re.DOTALL)):
        load_boundaries(geo)


@pytest.mark.parametrize(
    ("name", "text", "error"),
    [
        ("house.credit.txt", "", r"house\.credit\.txt.*one line"),
        ("senate.credit.txt", "  \n", r"senate\.credit\.txt.*one line"),
        ("house.credit.txt", "a\nb\n", r"house\.credit\.txt.*one line"),
        ("islands/credit.txt", "only one credit\n", r"credit\.txt.*does not match"),
        ("house.credit.txt", "Someone else\n", r"credit\.txt.*does not match"),
        ("house.geojson", "{", r"house\.geojson.*Invalid JSON"),
        ("islands/membership.json", "{", r"membership\.json.*line 1"),
        ("islands/membership.json", "[]", r"membership\.json.*valid dictionary"),
        ("islands/islands.json", "[]", r"islands\.json.*Input should be an object"),
    ],
)
def test_each_bad_text_file_is_rejected(tmp_path: Path, name: str, text: str, error: str) -> None:
    geo = copy_geo(tmp_path)
    (geo / name).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=re.compile(error, re.DOTALL)):
        load_boundaries(geo)


def test_a_key_repeated_in_membership_json_is_rejected_not_overwritten(tmp_path: Path) -> None:
    geo = copy_geo(tmp_path)
    path = geo / "islands/membership.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('"house-01": ["hawaii"],', '"house-01": ["hawaii"], "house-01": ["maui"],'),
        "utf-8",
    )
    with pytest.raises(ValueError, match=r"membership\.json.*duplicate.*house-01"):
        load_boundaries(geo)


@pytest.mark.parametrize(
    "name",
    [
        "house.geojson",
        "senate.geojson",
        "house.provenance.json",
        "senate.credit.txt",
        "islands/islands.json",
        "islands/membership.json",
        "islands/credit.txt",
    ],
)
def test_each_required_file_must_exist(tmp_path: Path, name: str) -> None:
    geo = copy_geo(tmp_path)
    (geo / name).unlink()
    with pytest.raises(OSError, match=re.escape(name)):
        load_boundaries(geo)


def coastline_geo(tmp_path: Path) -> Path:
    geo = copy_geo(tmp_path)
    build_islands(geo, geo / "islands", FIXTURES)
    return geo


def test_available_coastline_without_its_file_is_rejected(tmp_path: Path) -> None:
    geo = coastline_geo(tmp_path)
    (geo / "islands/coastlines.geojson").unlink()
    with pytest.raises(ValueError, match=r"no coastline geometry.*maui.*oahu"):
        load_boundaries(geo)


def test_available_coastline_without_its_feature_is_rejected(tmp_path: Path) -> None:
    geo = coastline_geo(tmp_path)
    edit_json(geo / "islands/coastlines.geojson", drop_first)
    with pytest.raises(ValueError, match=r"no coastline geometry.*maui"):
        load_boundaries(geo)


def test_geometry_for_an_unavailable_coastline_is_rejected(tmp_path: Path) -> None:
    geo = coastline_geo(tmp_path)
    edit_json(
        geo / "islands/coastlines.geojson",
        set_key("features", 0, "properties", "island", value="kauai"),
    )
    with pytest.raises(ValueError, match=r"coastline geometry.*unavailable.*kauai"):
        load_boundaries(geo)


def test_a_stale_coastline_file_is_rejected_when_all_are_unavailable(tmp_path: Path) -> None:
    geo = coastline_geo(tmp_path)
    shutil.copy(GEO / "islands/islands.json", geo / "islands/islands.json")
    shutil.copy(GEO / "islands/credit.txt", geo / "islands/credit.txt")
    with pytest.raises(ValueError, match=r"coastline geometry.*unavailable.*maui.*oahu"):
        load_boundaries(geo)


def test_a_repeated_coastline_feature_is_rejected(tmp_path: Path) -> None:
    geo = coastline_geo(tmp_path)
    edit_json(geo / "islands/coastlines.geojson", repeat_first)
    with pytest.raises(ValueError, match=r"duplicate coastline.*maui"):
        load_boundaries(geo)


def test_the_coastline_credit_must_be_attributed(tmp_path: Path) -> None:
    geo = coastline_geo(tmp_path)
    shutil.copy(GEO / "islands/credit.txt", geo / "islands/credit.txt")
    with pytest.raises(ValueError, match=r"credit\.txt.*does not match"):
        load_boundaries(geo)


def test_every_named_island_is_reachable_from_a_district() -> None:
    reached = {i.id for entry in load_boundaries().districts.values() for i in entry.islands}
    assert reached == set(ISLANDS)
