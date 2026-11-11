"""Census 2020 block-population crosswalk from Census places to 2022 State districts.

Fetch the inputs once (network), then rebuild offline from the cache:

    uv run python -m etl.district_places --fetch data/cache/places
    C=data/cache/places
    uv run python -m etl.district_places $C/tl_2020_15_tabblock20.zip \\
        $C/BlockAssign_ST15_HI.zip $C/sldl_2022.zip $C/sldu_2022.zip \\
        $C/2023_gaz_place_15.txt $C/state-house.geojson $C/state-senate.geojson \\
        data/district_places.tsv --retrieved-on YYYY-MM-DD

Inputs, unchanged from their publishers, in that order (``FETCH_NAMES``): TIGER/Line
2020 tabblock20 (POP20 and the internal point of each block); the 2020 Block Assignment
File (block to place, ``INCPLACE_CDP``); the Census 2022 State legislative block
equivalency files (block to SLDL and SLDU for the 2022 plan, released in 2023); the
2023 Gazetteer place file (names); and the State's full-resolution House and Senate
exports, fetched at exactly the ``source_url`` strings in
``data/district_counties.provenance.json`` (no ``maxAllowableOffset``, ``outSR=4326``).

Every block's internal point is checked against the State polygons of each chamber
(``--draft-review`` lists the blocks that need a review). A block whose point lands in
no district, or in another one, must be listed in ``data/places/block_review.tsv`` with
a resolution, or the build fails. Thresholds, equality and zero-denominator rules are
stated in ``docs/data.md``.
"""

import argparse
import csv
import hashlib
import io
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen
from zipfile import ZipFile

from pydantic import TypeAdapter

from etl.boundaries import expected_fact_keys
from etl.boundaries.overlay import shapefile

ROOT = Path(__file__).resolve().parents[1]
SPELLING_PATH = ROOT / "data/places/spelling.tsv"
REVIEW_PATH = ROOT / "data/places/block_review.tsv"
COUNTIES_PROVENANCE = ROOT / "data/district_counties.provenance.json"

Chamber = Literal["house", "senate"]
CHAMBERS: tuple[Chamber, ...] = ("house", "senate")

BLOCKS_SOURCE = "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_15_tabblock20.zip"
PLACE_SOURCE = "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST15_HI.zip"
_BEF = "https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2023/2022-state-legislative-bef/"
SLD_SOURCES: dict[Chamber, str] = {
    "house": _BEF + "sldl_2022.zip",
    "senate": _BEF + "sldu_2022.zip",
}
GAZETTEER_SOURCE = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_gaz_place_15.txt"
)
# Verbatim the county crosswalk's State queries (data/district_counties.provenance.json).
STATE_SOURCES: dict[Chamber, str] = {
    "house": "https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer/33/query?where=1%3D1&outFields=house_id&f=geojson&outSR=4326&returnGeometry=true",
    "senate": "https://geodata.hawaii.gov/arcgis/rest/services/AdminBnd/MapServer/34/query?where=1%3D1&outFields=senate_id&f=geojson&outSR=4326&returnGeometry=true",
}
PLACE_TABLE = "BlockAssign_ST15_HI_INCPLACE_CDP.txt"
SLD_TABLES: dict[Chamber, str] = {"house": "15_HI_SLDL22.txt", "senate": "15_HI_SLDU22.txt"}

# (role, cache file name, URL), in the CLI's positional order.
FETCH_NAMES: tuple[tuple[str, str, str], ...] = (
    ("blocks", "tl_2020_15_tabblock20.zip", BLOCKS_SOURCE),
    ("place", "BlockAssign_ST15_HI.zip", PLACE_SOURCE),
    ("sldl", "sldl_2022.zip", SLD_SOURCES["house"]),
    ("sldu", "sldu_2022.zip", SLD_SOURCES["senate"]),
    ("gazetteer", "2023_gaz_place_15.txt", GAZETTEER_SOURCE),
    ("house", "state-house.geojson", STATE_SOURCES["house"]),
    ("senate", "state-senate.geojson", STATE_SOURCES["senate"]),
)
ROLES = {
    "blocks": "POP20 and internal point of each 2020 tabulation block",
    "place": "2020 block to place (INCPLACE_CDP); the 2023 Gazetteer lists the same places",
    "sldl": "2020 block to 2022 State House district (Census block equivalency file)",
    "sldu": "2020 block to 2022 State Senate district (Census block equivalency file)",
    "gazetteer": "2023 place names (Census ASCII); display spellings come from spelling.tsv",
    "house": "State full-resolution House districts, for the block internal-point check",
    "senate": "State full-resolution Senate districts, for the block internal-point check",
}
# Plain sentences: step 2 shows this method in the brief.
METHOD = (
    "Census 2020 block counts. Census files put each block in a place and in a 2022 "
    "district, and each block's center point was checked against the State district map. "
    "The share is the place's residents who live in the district, divided by all residents "
    "of the place."
)
COLUMNS = (
    "district",
    "place_geoid",
    "name",
    "intersection_pop",
    "place_pop",
    "share",
    "qualifier",
    "block_source",
    "place_source",
    "pop_vintage",
    "plan",
    "method",
    "retrieved_on",
)
REVIEW_COLUMNS = (
    "chamber",
    "block",
    "pop20",
    "kind",
    "census_district",
    "point_districts",
    "resolution",
    "note",
)
UNMAPPABLE = "whole-place 2020 population is zero"

# Rules; docs/data.md is their only prose statement. Whole numbers, never rounded shares.
INCLUDE_SHARE = (1, 10)  # at least 1/10 of the place's residents ...
INCLUDE_RESIDENTS = 1000  # ... or at least 1,000 of them
MOST_SHARE = (1, 2)  # `most` above 1/2; exactly 1/2 is `part`

Point = tuple[float, float]
Ring = list[Point]
_rings = TypeAdapter(list[list[tuple[float, float]]])
_multi = TypeAdapter(list[list[list[tuple[float, float]]]])
_document = TypeAdapter(dict[str, Any])


def share(intersection: int, whole: int) -> float | None:
    """Intersection over whole-place population; None (unmappable) for a zero denominator."""
    return None if whole == 0 else intersection / whole


def included(intersection: int, whole: int) -> bool:
    if whole == 0 or intersection <= 0:
        return False
    numerator, denominator = INCLUDE_SHARE
    return intersection * denominator >= whole * numerator or intersection >= INCLUDE_RESIDENTS


def qualifier(intersection: int, whole: int) -> Literal["most", "part"]:
    if whole == 0:
        raise ValueError("a place with no residents has no share")
    numerator, denominator = MOST_SHARE
    return "most" if intersection * denominator > whole * numerator else "part"


@dataclass(frozen=True)
class Block:
    geoid: str
    pop: int
    point: Point


@dataclass(frozen=True)
class Problem:
    chamber: Chamber
    block: str
    pop: int
    kind: Literal["unmatched", "split"]
    census_district: str
    point_districts: tuple[str, ...]


@dataclass(frozen=True)
class Inputs:
    """Unchanged downloads, in ``FETCH_NAMES`` order (the CLI's positional order)."""

    blocks: Path
    place: Path
    sldl: Path
    sldu: Path
    gazetteer: Path
    house: Path
    senate: Path

    @classmethod
    def in_directory(cls, directory: Path) -> "Inputs":
        return cls(*(directory / name for _, name, _ in FETCH_NAMES))


class _Index:
    """Even-odd point-in-polygon over all rings, with edges bucketed into y bands."""

    BANDS = 512

    def __init__(self, rings: list[Ring]) -> None:
        edges = [(a, b) for ring in rings for a, b in pairwise(ring)]
        xs = [x for ring in rings for x, _ in ring]
        ys = [y for ring in rings for _, y in ring]
        self.box = (min(xs), min(ys), max(xs), max(ys))
        height = (self.box[3] - self.box[1]) or 1.0
        self.step = height / self.BANDS
        self.bands: list[list[tuple[Point, Point]]] = [[] for _ in range(self.BANDS)]
        for a, b in edges:
            if a[1] == b[1]:
                continue
            low, high = sorted((self._band(a[1]), self._band(b[1])))
            for band in range(low, high + 1):
                self.bands[band].append((a, b))

    def _band(self, y: float) -> int:
        return min(self.BANDS - 1, max(0, int((y - self.box[1]) / self.step)))

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.box
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        inside = False
        for (ax, ay), (bx, by) in self.bands[self._band(y)]:
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
        return inside


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fold(name: str) -> str:
    """Drop the ʻokina and kahakō so a display spelling can be checked against Census ASCII."""
    decomposed = unicodedata.normalize("NFD", name.replace("ʻ", ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _read_member(archive: Path, name: str) -> bytes:
    with ZipFile(archive) as zipped:
        if zipped.namelist().count(name) != 1:
            raise ValueError(f"{archive.name} requires exactly one {name}")
        return zipped.read(name)


def load_blocks(path: Path) -> dict[str, Block]:
    """Read POP20 and the internal point of every Hawaiʻi 2020 tabulation block."""
    with ZipFile(path) as archive:
        dbfs = [name for name in archive.namelist() if name.endswith(".dbf")]
        if len(dbfs) != 1:
            raise ValueError("block archive requires exactly one .dbf member")
        dbf = archive.read(dbfs[0])
    blocks: dict[str, Block] = {}
    with shapefile.Reader(dbf=io.BytesIO(dbf)) as reader:
        for record in reader.iterRecords():
            row: dict[str, Any] = record.as_dict()
            geoid = str(row["GEOID20"])
            if row["STATEFP20"] != "15" or len(geoid) != 15 or not geoid.startswith("15"):
                raise ValueError(f"block outside Hawaiʻi or malformed: {geoid}")
            pop = row["POP20"]
            if not isinstance(pop, int) or pop < 0:
                raise ValueError(f"block population must be a whole number: {geoid}")
            if geoid in blocks:
                raise ValueError(f"duplicate block: {geoid}")
            point = (float(row["INTPTLON20"]), float(row["INTPTLAT20"]))
            blocks[geoid] = Block(geoid, pop, point)
    if not blocks:
        raise ValueError("no blocks")
    return blocks


def load_assignment(
    path: Path, table: str, header: tuple[str, str], blocks: dict[str, Block]
) -> dict[str, str]:
    """Read one block → code table; its block set must equal the 2020 tabulation blocks."""
    text = _read_member(path, table).decode("utf-8-sig")
    lines = text.splitlines()
    delimiter = "|" if "|" in lines[0] else ","
    if tuple(lines[0].split(delimiter)) != header:
        raise ValueError(f"unexpected header in {table}")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        parts = line.split(delimiter)
        if len(parts) != 2:
            raise ValueError(f"malformed row in {table}: {line}")
        if parts[0] in result:
            raise ValueError(f"duplicate block in {table}: {parts[0]}")
        result[parts[0]] = parts[1]
    if result.keys() != blocks.keys():
        missing, extra = len(blocks.keys() - result.keys()), len(result.keys() - blocks.keys())
        raise ValueError(f"{table} block set mismatch: missing={missing}, extra={extra}")
    return result


def load_gazetteer(path: Path) -> dict[str, str]:
    """Place GEOID → Census NAME from the Gazetteer place file."""
    result: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")), delimiter="\t"):
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        geoid = clean["GEOID"]
        if clean["USPS"] != "HI" or not geoid.startswith("15") or len(geoid) != 7:
            raise ValueError(f"gazetteer place outside Hawaiʻi: {geoid}")
        if geoid in result:
            raise ValueError(f"duplicate gazetteer place: {geoid}")
        result[geoid] = clean["NAME"]
    return result


def load_spelling(path: Path, census_names: set[str]) -> dict[str, str]:
    """Census name → checked display spelling; every listed name must be a Census place."""
    result: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            source, display, reference = (
                (row.get(k) or "").strip() for k in ("source_name", "display_name", "reference")
            )
            if source in result:
                raise ValueError(f"duplicate spelling entry: {source}")
            if source not in census_names:
                raise ValueError(f"listed name missing from Census places: {source}")
            if not display or not reference:
                raise ValueError(f"spelling entry needs a display name and reference: {source}")
            if unicodedata.normalize("NFC", display) != display:
                raise ValueError(f"display name must be NFC-normalized: {display}")
            if any(c in display for c in "'\u2018\u2019`"):  # apostrophe and turned quotes
                raise ValueError(f"display name must use the ʻokina (U+02BB): {display}")
            if fold(display) != source.removesuffix(" CDP"):
                raise ValueError(f"display name does not spell the Census name: {display}")
            result[source] = display
    return result


def load_state(path: Path, chamber: Chamber) -> dict[str, list[Ring]]:
    """Raw State ArcGIS GeoJSON → fact key → rings of every polygon (holes included)."""
    document = _document.validate_json(path.read_bytes())
    extra = _document.validate_python(document.get("properties") or {})
    if document.get("exceededTransferLimit") or extra.get("exceededTransferLimit"):
        raise ValueError(f"incomplete State export: {chamber}")
    result: dict[str, list[Ring]] = {}
    for feature in TypeAdapter(list[dict[str, Any]]).validate_python(document["features"]):
        number = int(feature["properties"][f"{chamber}_id"])
        key = f"{chamber}:15:{number:03d}:2022"
        if key in result:
            raise ValueError(f"duplicate State district: {key}")
        geometry: dict[str, Any] = feature["geometry"]
        if geometry["type"] == "Polygon":
            polygons = [_rings.validate_python(geometry["coordinates"])]
        elif geometry["type"] == "MultiPolygon":
            polygons = _multi.validate_python(geometry["coordinates"])
        else:
            raise ValueError(f"State {chamber} geometry must be polygonal: {key}")
        result[key] = [ring for polygon in polygons for ring in polygon]
    if result.keys() != expected_fact_keys(chamber):
        raise ValueError(f"State {chamber} district set mismatch")
    return result


def verify_blocks(
    chamber: Chamber, blocks: dict[str, Block], codes: dict[str, str], districts: dict[str, _Index]
) -> tuple[dict[str, str], list[Problem]]:
    """Census district per block, and every block whose internal point disagrees with it."""
    assigned: dict[str, str] = {}
    problems: list[Problem] = []
    for geoid, block in blocks.items():
        census = f"{chamber}:15:{codes[geoid]}:2022"
        if census not in districts:
            raise ValueError(f"block {geoid} has no 2022 {chamber} district: {codes[geoid]!r}")
        assigned[geoid] = census
        hits = tuple(sorted(k for k, index in districts.items() if index.contains(*block.point)))
        if hits == (census,):
            continue
        kind: Literal["unmatched", "split"] = "split" if hits else "unmatched"
        problems.append(Problem(chamber, geoid, block.pop, kind, census, hits))
    return assigned, problems


def write_review(path: Path, problems: list[Problem]) -> None:
    """Draft a review file: every problem block, with an empty resolution to fill in."""
    rows = [
        [
            p.chamber,
            p.block,
            str(p.pop),
            p.kind,
            p.census_district,
            " ".join(p.point_districts),
            "",
            "",
        ]
        for p in sorted(problems, key=lambda p: (p.chamber, p.block))
    ]
    _write_tsv(path, REVIEW_COLUMNS, rows)


def apply_review(
    path: Path, problems: list[Problem], assigned: dict[Chamber, dict[str, str]]
) -> Counter[str]:
    """Resolve each problem block from the review file; unreviewed or stale rows fail."""
    with path.open(encoding="utf-8", newline="") as stream:
        reviewed = {
            (row["chamber"], row["block"]): row for row in csv.DictReader(stream, delimiter="\t")
        }
    wanted = {(p.chamber, p.block): p for p in problems}
    missing = sorted(wanted.keys() - reviewed.keys())
    if missing:
        listed = ", ".join(":".join(k) for k in missing[:5])
        raise ValueError(
            f"{len(missing)} unmatched or split blocks lack a review in {path.name}: {listed}"
        )
    stale = sorted(reviewed.keys() - wanted.keys())
    if stale:
        listed = ", ".join(":".join(k) for k in stale[:5])
        raise ValueError(f"block review lists blocks that need no review: {listed}")
    resolutions: Counter[str] = Counter()
    for key, problem in sorted(wanted.items()):
        row = reviewed[key]
        facts = (str(problem.pop), problem.kind, problem.census_district)
        if (row["pop20"], row["kind"], row["census_district"]) != facts or row[
            "point_districts"
        ] != " ".join(problem.point_districts):
            raise ValueError(f"block review does not match the inputs: {':'.join(key)}")
        if not (row.get("note") or "").strip():
            raise ValueError(f"block review needs a note: {':'.join(key)}")
        resolution = row["resolution"]
        chamber_map = assigned[problem.chamber]
        if resolution == "census":
            pass
        elif resolution == "point" and len(problem.point_districts) == 1:
            chamber_map[problem.block] = problem.point_districts[0]
        elif resolution == "none":
            if problem.pop:
                raise ValueError(f"block {problem.block} has residents and cannot be dropped")
            del chamber_map[problem.block]
        else:
            raise ValueError(f"invalid block resolution {resolution!r}: {':'.join(key)}")
        resolutions[f"{problem.chamber} {problem.kind} {resolution}"] += 1
    return resolutions


def _write_tsv(path: Path, columns: tuple[str, ...], rows: list[list[str]]) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def find_problems(
    inputs: Inputs, blocks: dict[str, Block]
) -> tuple[dict[Chamber, dict[str, str]], list[Problem]]:
    assigned: dict[Chamber, dict[str, str]] = {}
    problems: list[Problem] = []
    for chamber in CHAMBERS:
        path, table_path = (
            (inputs.house, inputs.sldl) if chamber == "house" else (inputs.senate, inputs.sldu)
        )
        state = {key: _Index(rings) for key, rings in load_state(path, chamber).items()}
        code = "SLDLST" if chamber == "house" else "SLDUST"
        codes = load_assignment(table_path, SLD_TABLES[chamber], ("GEOID", code), blocks)
        assigned[chamber], found = verify_blocks(chamber, blocks, codes, state)
        problems.extend(found)
    return assigned, problems


def check_state_sources(sources: dict[Chamber, str], counties_provenance: Path) -> None:
    """The State queries must be the county crosswalk's, verbatim."""
    document = json.loads(counties_provenance.read_text(encoding="utf-8"))
    urls = [str(s["provenance"]["source_url"]) for s in document["district_sources"]]
    for chamber in CHAMBERS:
        if sources[chamber] not in urls or "maxAllowableOffset" in sources[chamber]:
            raise ValueError(f"{chamber} source is not the counties State query")


def build_places(
    inputs: Inputs,
    output: Path,
    *,
    retrieved_on: str,
    spelling: Path = SPELLING_PATH,
    review: Path = REVIEW_PATH,
    counties_provenance: Path = COUNTIES_PROVENANCE,
    sources: dict[Chamber, str] = STATE_SOURCES,
) -> None:
    """Validate everything first; write the TSV and its sidecar only when all checks pass."""
    check_state_sources(sources, counties_provenance)
    blocks = load_blocks(inputs.blocks)
    gazetteer = load_gazetteer(inputs.gazetteer)
    spellings = load_spelling(spelling, set(gazetteer.values()))
    place_codes = load_assignment(inputs.place, PLACE_TABLE, ("BLOCKID", "PLACEFP"), blocks)
    places = {geoid: "15" + code for geoid, code in place_codes.items() if code}
    unknown = sorted(set(places.values()) - gazetteer.keys())
    if unknown:
        raise ValueError(f"block places missing from the gazetteer: {', '.join(unknown)}")
    assigned, problems = find_problems(inputs, blocks)
    resolutions = apply_review(review, problems, assigned)

    place_pop: Counter[str] = Counter({geoid: 0 for geoid in gazetteer})
    for block, place in places.items():
        place_pop[place] += blocks[block].pop
    inside: Counter[tuple[str, str]] = Counter()
    for chamber in CHAMBERS:
        for block, district in assigned[chamber].items():
            if block in places:
                inside[(district, places[block])] += blocks[block].pop

    rows: list[list[str]] = []
    for (district, place), count in sorted(inside.items()):
        whole = place_pop[place]
        value = share(count, whole)
        if value is None or not included(count, whole):
            continue
        name = gazetteer[place]
        if name not in spellings:
            raise ValueError(f"place name missing from {spelling.name}: {name}")
        rows.append(
            [
                district,
                place,
                spellings[name],
                str(count),
                str(whole),
                f"{value:.6f}",
                qualifier(count, whole),
                BLOCKS_SOURCE,
                PLACE_SOURCE,
                "2020",
                "2022",
                METHOD,
                retrieved_on,
            ]
        )
    missing = sorted(expected_fact_keys() - {row[0] for row in rows})
    if missing:
        raise ValueError(f"districts with no listed place: {', '.join(missing)}")
    unmappable = [
        {
            "place_geoid": place,
            "name": spellings.get(gazetteer[place], gazetteer[place]),
            "reason": UNMAPPABLE,
        }
        for place in sorted(gazetteer)
        if place_pop[place] == 0
    ]
    paths = {
        "blocks": inputs.blocks,
        "place": inputs.place,
        "sldl": inputs.sldl,
        "sldu": inputs.sldu,
        "gazetteer": inputs.gazetteer,
        "house": inputs.house,
        "senate": inputs.senate,
    }
    urls = {role: url for role, _, url in FETCH_NAMES} | {
        "house": sources["house"],
        "senate": sources["senate"],
    }
    sidecar = {
        "inputs": [
            {"role": role, "url": urls[role], "sha256": sha256(path)}
            for role, path in paths.items()
        ],
        "retrieved_on": retrieved_on,
        "roles": ROLES,
        "state_geometry": (
            "The House and Senate exports are fetched at the county crosswalk's State query "
            "URLs, verbatim, on a later date. Their sha256 values are of the raw responses "
            "read here and are not expected to match the county sidecar's, which hash a "
            "re-serialized file."
        ),
        "blocks": {"count": len(blocks), "pop20": sum(b.pop for b in blocks.values())},
        "block_review": {
            "file": review.name,
            "sha256": sha256(review),
            "unmatched": sum(p.kind == "unmatched" for p in problems),
            "split": sum(p.kind == "split" for p in problems),
            "resolutions": dict(sorted(resolutions.items())),
        },
        "spelling": {"file": spelling.name, "sha256": sha256(spelling)},
        "unmappable_places": unmappable,
        "rules": {
            "include_share_at_least": f"{INCLUDE_SHARE[0]}/{INCLUDE_SHARE[1]}",
            "include_residents_at_least": INCLUDE_RESIDENTS,
            "most_share_above": f"{MOST_SHARE[0]}/{MOST_SHARE[1]}",
        },
        "rows": len(rows),
        "method": METHOD,
    }
    _write_tsv(output, COLUMNS, rows)
    output.with_suffix(".provenance.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def fetch(directory: Path) -> None:
    """Download every input, unchanged, into ``directory`` (a git-ignored cache)."""
    directory.mkdir(parents=True, exist_ok=True)
    for _, name, url in FETCH_NAMES:
        with urlopen(url, timeout=600) as response:
            data: bytes = response.read()
        (directory / name).write_bytes(data)
        print(f"{name}\t{hashlib.sha256(data).hexdigest()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", metavar="DIR", type=Path, help="download inputs to DIR")
    parser.add_argument("--retrieved-on")
    parser.add_argument(
        "--draft-review", metavar="TSV", type=Path, help="write every problem block to TSV"
    )
    parser.add_argument("paths", nargs="*", type=Path, metavar="PATH")
    args = parser.parse_args()
    if args.fetch is not None:
        fetch(args.fetch)
        return
    names = " ".join(role.upper() for role, _, _ in FETCH_NAMES)
    if len(args.paths) != len(FETCH_NAMES) + 1:
        parser.error(f"give {names} OUTPUT ({len(FETCH_NAMES) + 1} paths), not {len(args.paths)}")
    if args.draft_review is None and not args.retrieved_on:
        parser.error("give --retrieved-on YYYY-MM-DD, the date the inputs were fetched")
    inputs = Inputs(*args.paths[:-1])
    if args.draft_review is not None:
        _, problems = find_problems(inputs, load_blocks(inputs.blocks))
        write_review(args.draft_review, problems)
        return
    build_places(inputs, args.paths[-1], retrieved_on=args.retrieved_on)


if __name__ == "__main__":
    main()
