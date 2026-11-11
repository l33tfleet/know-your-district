"""WO424 (step 1 of #262): the Census place crosswalk, built offline from synthetic inputs.

Pins the decisions the work order states: inclusion and `part of` thresholds with their
equality rules, a zero whole-place denominator is unmappable (never a zero share), a
listed spelling missing from the Census places fails the build, every unmatched or split
block needs a reviewed resolution, and the State exports must be the counties queries.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile

import pytest

from etl.boundaries.overlay import shapefile
from etl.district_places import (
    STATE_SOURCES,
    Inputs,
    build_places,
    included,
    qualifier,
    share,
)

COUNTIES_PROVENANCE = Path(__file__).resolve().parents[2] / "data/district_counties.provenance.json"


def senate_for(x: float) -> int:
    return min(25, int(x // 2) + 1)


@dataclass
class Fixture:
    """Synthetic Hawaiʻi: House district i is the square x∈[i-1, i], y∈[0, 1]."""

    root: Path
    # block GEOID → (pop, x, y, place code or "")
    blocks: dict[str, tuple[int, float, float, str]] = field(default_factory=lambda: {})
    places: dict[str, str] = field(default_factory=lambda: {})
    spelling: dict[str, str] = field(default_factory=lambda: {})
    review: list[dict[str, str]] = field(default_factory=lambda: [])
    # block GEOID → (House, Senate) number the Census files give, overriding the point
    census: dict[str, tuple[int, int]] = field(default_factory=lambda: {})
    house_source: str = STATE_SOURCES["house"]

    def __post_init__(self) -> None:
        # One populated place per House district, wholly inside it.
        for i in range(1, 52):
            code = f"{i:05d}"
            self.places[code] = f"Town {i} CDP"
            self.spelling[f"Town {i} CDP"] = f"Town {i}"
            self.blocks[f"1500100010{i:05d}"] = (100, i - 0.5, 0.5, code)

    def district(self, geoid: str, x: float) -> tuple[int, int]:
        return self.census.get(geoid, (int(x // 1) + 1, senate_for(x)))

    def build(self) -> Path:
        root = self.root
        blocks = root / "blocks.zip"
        shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=1) as writer:
            for name in ("STATEFP20", "GEOID20", "INTPTLAT20", "INTPTLON20"):
                writer.field(name, "C")
            writer.field("POP20", "N", 9, 0)
            for geoid, (pop, x, y, _) in sorted(self.blocks.items()):
                writer.record("15", geoid, f"{y:+.7f}", f"{x:+.7f}", pop)
                writer.point(x, y)
        with ZipFile(blocks, "w") as archive:
            for suffix, stream in (("shp", shp), ("shx", shx), ("dbf", dbf)):
                archive.writestr(f"tl_2020_15_tabblock20.{suffix}", stream.getvalue())
        place = root / "baf.zip"
        with ZipFile(place, "w") as archive:
            archive.writestr(
                "BlockAssign_ST15_HI_INCPLACE_CDP.txt",
                "BLOCKID|PLACEFP\n"
                + "".join(f"{g}|{p}\n" for g, (_, _, _, p) in sorted(self.blocks.items())),
            )
        for code in ("SLDL", "SLDU"):
            with ZipFile(root / f"{code.lower()}.zip", "w") as archive:
                rows = "".join(
                    f"{g},{self.district(g, x)[0 if code == 'SLDL' else 1]:03d}\r\n"
                    for g, (_, x, _, _) in sorted(self.blocks.items())
                )
                archive.writestr(f"15_HI_{code}22.txt", f"GEOID,{code}ST\r\n{rows}")
        gazetteer = root / "gaz.txt"
        gazetteer.write_text(
            "USPS\tGEOID\tNAME\n"
            + "".join(f"HI\t15{c}\t{n}\n" for c, n in sorted(self.places.items())),
            encoding="utf-8",
        )
        for chamber, count, span in (("house", 51, None), ("senate", 25, 2)):
            features: list[dict[str, object]] = []
            for n in range(1, count + 1):
                left, right = (n - 1, n) if span is None else (2 * n - 2, 51 if n == 25 else 2 * n)
                ring = [[left, 0], [right, 0], [right, 1], [left, 1], [left, 0]]
                features.append(
                    {
                        "type": "Feature",
                        "id": n,
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                        "properties": {f"{chamber}_id": n},
                    }
                )
            (root / f"state-{chamber}.geojson").write_text(
                json.dumps({"type": "FeatureCollection", "features": features})
            )
        spelling = root / "spelling.tsv"
        spelling.write_text(
            "source_name\tdisplay_name\treference\n"
            + "".join(f"{s}\t{d}\tHBGN via GNIS 1\n" for s, d in sorted(self.spelling.items())),
            encoding="utf-8",
        )
        review = root / "block_review.tsv"
        columns = ["chamber", "block", "pop20", "kind", "census_district", "point_districts"]
        with review.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[*columns, "resolution", "note"],
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(self.review)
        output = root / "district_places.tsv"
        build_places(
            Inputs(
                blocks=blocks,
                place=place,
                sldl=root / "sldl.zip",
                sldu=root / "sldu.zip",
                gazetteer=gazetteer,
                house=root / "state-house.geojson",
                senate=root / "state-senate.geojson",
            ),
            output,
            retrieved_on="2026-11-11",
            spelling=spelling,
            review=review,
            counties_provenance=COUNTIES_PROVENANCE,
            sources={"house": self.house_source, "senate": STATE_SOURCES["senate"]},
        )
        return output


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"))


def test_inclusion_threshold_counts_equality() -> None:
    # At least 1/10 of the place, or at least 1,000 residents: both equalities count.
    assert included(10, 100)
    assert not included(9, 100)
    assert included(1000, 1_000_000)
    assert not included(999, 1_000_000)
    assert not included(0, 100)


def test_part_of_threshold_exactly_half_is_part() -> None:
    assert qualifier(51, 100) == "most"
    assert qualifier(50, 100) == "part"
    assert qualifier(100, 100) == "most"


def test_zero_denominator_is_unmappable_not_zero() -> None:
    assert share(0, 0) is None
    assert share(0, 10) == 0
    with pytest.raises(ValueError, match="no residents"):
        qualifier(0, 0)
    assert not included(0, 0)


def test_build_writes_76_districts_shares_and_spelling(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    # A place split 1/2 and 1/2 between House 1 and 2 is `part` in each.
    fixture.places["90000"] = "Split CDP"
    fixture.spelling["Split CDP"] = "Split"
    fixture.blocks["150010002000001"] = (40, 0.25, 0.25, "90000")
    fixture.blocks["150010002000002"] = (40, 1.25, 0.25, "90000")
    output = fixture.build()
    table = rows(output)
    assert {r["district"] for r in table} == {
        f"{c}:15:{n:03d}:2022" for c, k in (("house", 51), ("senate", 25)) for n in range(1, k + 1)
    }
    split = [r for r in table if r["place_geoid"] == "1590000"]
    assert [(r["district"], r["share"], r["qualifier"]) for r in split] == [
        ("house:15:001:2022", "0.500000", "part"),
        ("house:15:002:2022", "0.500000", "part"),
        ("senate:15:001:2022", "1.000000", "most"),
    ]
    assert {r["name"] for r in table} <= set(fixture.spelling.values())
    assert all(r["pop_vintage"] == "2020" and r["plan"] == "2022" for r in table)
    sidecar = json.loads(output.with_suffix(".provenance.json").read_text())
    state = {i["role"]: i for i in sidecar["inputs"]}
    assert state["house"]["url"] == STATE_SOURCES["house"]
    assert len(state["house"]["sha256"]) == 64
    assert sidecar["retrieved_on"] == "2026-11-11"
    first = output.read_bytes()
    fixture.build()
    assert output.read_bytes() == first


def test_zero_population_place_gets_no_row_and_is_listed_unmappable(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.places["90000"] = "Empty CDP"
    fixture.spelling["Empty CDP"] = "Empty"
    fixture.blocks["150010002000001"] = (0, 0.25, 0.25, "90000")
    output = fixture.build()
    assert not [r for r in rows(output) if r["place_geoid"] == "1590000"]
    sidecar = json.loads(output.with_suffix(".provenance.json").read_text())
    assert sidecar["unmappable_places"] == [
        {"place_geoid": "1590000", "name": "Empty", "reason": "whole-place 2020 population is zero"}
    ]


def test_listed_spelling_missing_from_census_places_fails(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.spelling["Atlantis CDP"] = "Atlantis"
    with pytest.raises(ValueError, match="listed name missing from Census places: Atlantis CDP"):
        fixture.build()
    assert not (tmp_path / "district_places.tsv").exists()


def test_place_without_spelling_fails(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    del fixture.spelling["Town 7 CDP"]
    with pytest.raises(ValueError, match=r"place name missing from .*Town 7 CDP"):
        fixture.build()


@pytest.mark.parametrize("display", ["Hawai'i", "Hawai\u2018i", "Hilo"])
def test_bad_display_spelling_fails(tmp_path: Path, display: str) -> None:
    fixture = Fixture(tmp_path)
    fixture.places["90000"] = "Hawaii CDP"
    fixture.spelling["Hawaii CDP"] = display
    fixture.blocks["150010002000001"] = (5, 0.25, 0.25, "90000")
    with pytest.raises(ValueError, match="display name"):
        fixture.build()


def test_unmatched_block_fails_unless_reviewed(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    # Internal point off every State polygon (y > 1), Census says House 3 / Senate 2.
    fixture.blocks["150010002000009"] = (12, 2.5, 5.0, "00003")
    with pytest.raises(ValueError, match="unmatched or split blocks lack a review"):
        fixture.build()
    assert not (tmp_path / "district_places.tsv").exists()
    for chamber, district in (("house", "house:15:003:2022"), ("senate", "senate:15:002:2022")):
        fixture.review.append(
            {
                "chamber": chamber,
                "block": "150010002000009",
                "pop20": "12",
                "kind": "unmatched",
                "census_district": district,
                "point_districts": "",
                "resolution": "census",
                "note": "Off the State coastline; the Census district is kept.",
            }
        )
    output = fixture.build()
    town = [r for r in rows(output) if r["place_geoid"] == "1500003"]
    assert [(r["district"], r["intersection_pop"]) for r in town] == [
        ("house:15:003:2022", "112"),
        ("senate:15:002:2022", "112"),
    ]
    sidecar = json.loads(output.with_suffix(".provenance.json").read_text())
    assert sidecar["block_review"]["unmatched"] == 2


def test_populated_block_cannot_be_dropped(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.blocks["150010002000009"] = (12, 2.5, 5.0, "00003")
    for chamber, district in (("house", "house:15:003:2022"), ("senate", "senate:15:002:2022")):
        fixture.review.append(
            {
                "chamber": chamber,
                "block": "150010002000009",
                "pop20": "12",
                "kind": "unmatched",
                "census_district": district,
                "point_districts": "",
                "resolution": "none",
                "note": "dropped",
            }
        )
    with pytest.raises(ValueError, match="has residents"):
        fixture.build()


def test_split_block_is_reviewed(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    # Census puts the block in House 1, but its point lands in House 2: a split.
    fixture.blocks["150010002000009"] = (30, 1.5, 0.5, "00001")
    fixture.census["150010002000009"] = (1, 1)
    with pytest.raises(ValueError, match="unmatched or split blocks lack a review"):
        fixture.build()
    fixture.review.append(
        {
            "chamber": "house",
            "block": "150010002000009",
            "pop20": "30",
            "kind": "split",
            "census_district": "house:15:001:2022",
            "point_districts": "house:15:002:2022",
            "resolution": "point",
            "note": "The point lies well inside House 2 on the State map.",
        }
    )
    output = fixture.build()
    town = [r for r in rows(output) if r["place_geoid"] == "1500001"]
    assert [(r["district"], r["intersection_pop"], r["share"]) for r in town] == [
        ("house:15:001:2022", "100", "0.769231"),
        ("house:15:002:2022", "30", "0.230769"),
        ("senate:15:001:2022", "130", "1.000000"),
    ]
    sidecar = json.loads(output.with_suffix(".provenance.json").read_text())
    assert sidecar["block_review"]["split"] == 1
    assert sidecar["block_review"]["resolutions"] == {"house split point": 1}


def test_stale_review_row_fails(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.review.append(
        {
            "chamber": "house",
            "block": "150010001000001",
            "pop20": "100",
            "kind": "split",
            "census_district": "house:15:001:2022",
            "point_districts": "house:15:002:2022",
            "resolution": "census",
            "note": "Not a problem block.",
        }
    )
    with pytest.raises(ValueError, match="block review lists blocks that need no review"):
        fixture.build()


def test_state_export_must_be_the_counties_query(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.house_source = STATE_SOURCES["house"] + "&maxAllowableOffset=0.0005"
    with pytest.raises(ValueError, match="not the counties State query"):
        fixture.build()


def test_missing_state_district_fails(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.build()
    path = tmp_path / "state-senate.geojson"
    document = json.loads(path.read_text())
    document["features"].pop()
    (tmp_path / "district_places.tsv").unlink()
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="State senate district set mismatch"):
        build_places(
            Inputs(
                blocks=tmp_path / "blocks.zip",
                place=tmp_path / "baf.zip",
                sldl=tmp_path / "sldl.zip",
                sldu=tmp_path / "sldu.zip",
                gazetteer=tmp_path / "gaz.txt",
                house=tmp_path / "state-house.geojson",
                senate=path,
            ),
            tmp_path / "district_places.tsv",
            retrieved_on="2026-11-11",
            spelling=tmp_path / "spelling.tsv",
            review=tmp_path / "block_review.tsv",
            counties_provenance=COUNTIES_PROVENANCE,
        )
    assert not (tmp_path / "district_places.tsv").exists()
