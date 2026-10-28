"""WO121: complete county coverage, area splits and cited county comparisons offline."""

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.counties as counties
from app.main import app
from etl.boundaries import expected_fact_keys
from etl.boundaries.counties import area_shares
from tests.regressions.test_wo97_brief_page import (
    VARIABLES,
    brief,
    build_db,
    check_citation,
    check_reading,
    row,
)

ROOT = Path(__file__).resolve().parents[2]


def test_committed_mapping_covers_all_76_and_known_districts() -> None:
    mapping = counties.load_mapping()
    assert set(mapping) == expected_fact_keys()
    for key, code in [
        ("house:15:001:2022", "001"),
        ("house:15:009:2022", "009"),
        ("house:15:022:2022", "003"),
        ("senate:15:008:2022", "007"),
    ]:
        assert [share.county for share in mapping[key]] == [f"county:15:{code}"]
    for shares in mapping.values():
        assert sum(share.area_share for share in shares) == pytest.approx(1)
        assert all(s.county != "county:15:005" for s in shares)


def test_unmapped_district_fails(tmp_path: Path) -> None:
    source = ROOT / "data/district_counties.tsv"
    lines = source.read_text().splitlines()
    path = tmp_path / "missing.tsv"
    path.write_text(
        "\n".join(line for line in lines if not line.startswith("house:15:001:2022\t")) + "\n"
    )
    with pytest.raises(ValueError, match=r"district set mismatch.*house:15:001:2022"):
        counties.load_mapping(path)


def box(left: float, right: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[left, 0], [right, 0], [right, 2], [left, 2], [left, 0]]],
    }


def test_area_split_and_touching_county() -> None:
    assert area_shares(
        box(0, 4), {"001": box(0, 1), "009": box(1, 4), "003": box(4, 5)}
    ) == pytest.approx({"001": 0.25, "009": 0.75})


def test_no_county_overlap_fails() -> None:
    with pytest.raises(ValueError, match="no county overlap"):
        area_shares(box(0, 1), {"001": box(2, 3)})


@pytest.mark.parametrize("split", [False, True])
def test_county_values_moes_and_citations_beside_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, split: bool
) -> None:
    mapping_path = tmp_path / "counties.tsv"
    with (ROOT / "data/district_counties.tsv").open() as stream:
        records = list(csv.DictReader(stream, delimiter="\t"))
    if split:
        original = next(r for r in records if r["district"] == "house:15:022:2022")
        original["area_share"] = "0.75"
        records.append(original | {"county": "county:15:009", "area_share": "0.25"})
    with mapping_path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(records)
    monkeypatch.setattr(counties, "MAPPING_PATH", mapping_path)
    geographies = ["house:15:022:2022", "state:15", "county:15:003"]
    if split:
        geographies.append("county:15:009")
    facts = [
        row(f, g, 1234 + i * 100, 12 + i) for f in VARIABLES for i, g in enumerate(geographies)
    ]
    db = tmp_path / "facts.db"
    build_db(db, facts)
    monkeypatch.setenv("KYD_FACTS_DB", str(db))
    page = brief(TestClient(app), "/brief/house/22")
    for node in page.find_all(class_="figure"):
        figure = node.attrs["data-figure"]
        for geography in geographies:
            fact = next(
                f for f in facts if f.geography == geography and f.variable == VARIABLES[figure][0]
            )
            check_reading(node.one(class_="reading", data_geography=geography), fact, figure)
            check_citation(node.one("dl", data_geography=geography), fact)
    assert "Honolulu County" in page.text
    if split:
        assert "more than one county" in page.text
        assert "Maui County" in page.text
        assert "75.0%" in page.text and "25.0%" in page.text
        assert "area" in page.text


@pytest.mark.parametrize(
    "change,message",
    [
        ("county", "excluded or unknown county: county:15:005"),
        ("duplicate", "duplicate district/county: house:15:001:2022"),
        ("sum", "area shares must sum to one: house:15:001:2022"),
        ("zero", "greater than 0"),
        ("over_one", "less than or equal to 1"),
        ("nonfinite", "finite number"),
    ],
)
def test_invalid_mapping_fails(tmp_path: Path, change: str, message: str) -> None:
    with (ROOT / "data/district_counties.tsv").open() as stream:
        records = list(csv.DictReader(stream, delimiter="\t"))
    if change == "county":
        records[0]["county"] = "county:15:005"
    elif change == "duplicate":
        records.append(records[0].copy())
    else:
        records[0]["area_share"] = {
            "sum": "0.5",
            "zero": "0",
            "over_one": "1.1",
            "nonfinite": "nan",
        }[change]
    path = tmp_path / "invalid.tsv"
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(records)
    with pytest.raises(ValueError, match=message):
        counties.load_mapping(path)
