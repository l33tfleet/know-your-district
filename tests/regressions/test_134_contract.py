"""Synthetic contract fixtures for #168; no published tax observations."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.zip_contract import CrosswalkRow, TaxObservation, UnmappableZIP, read_crosswalk, read_tax


def tax() -> dict[str, object]:
    return dict(
        zip="00123",
        measure="median_agi",
        filing_status="single",
        year=2022,
        units="USD",
        value="123.45",
        status="published",
        table="Table 1",
        source_url="https://files.hawaii.gov/tax/example.pdf",
        retrieved_on="2026-10-29",
    )


def crosswalk() -> dict[str, object]:
    return dict(
        zcta="00123",
        district=dict(chamber="house", district=1),
        intersection_population=20,
        zcta_population=100,
        district_population=200,
        population_year=2020,
        method="population-weighted (2020 blocks)",
        source_url="https://www.census.gov/example",
        retrieved_on="2026-10-29",
    )


def test_tax_identity_suppression_and_reader_roundtrip(tmp_path: Path) -> None:
    rows = [
        tax(),
        tax() | dict(year=2021),
        tax() | dict(filing_status="joint"),
        tax() | dict(measure="returns", value=None, status="suppressed"),
    ]
    path = tmp_path / "tax.json"
    path.write_text(json.dumps(rows))
    records = read_tax(path)
    assert len({row.key for row in records}) == 4
    assert records[0].key == ("00123", "median_agi", "single", 2022)
    assert str(records[0].value) == "123.45"
    assert records[-1].value is None and records[-1].status == "suppressed"
    assert TaxObservation.model_validate_json(records[-1].model_dump_json()) == records[-1]


@pytest.mark.parametrize(
    "change, error",
    [
        (dict(zip="123"), "zip"),
        (dict(zip="\uff11\uff12\uff13\uff14\uff15"), "zip"),
        (dict(year=2022.5), "year"),
        (dict(year=True), "year"),
        (dict(filing_status=""), "filing_status"),
        (dict(measure="x?y"), "measure"),
        (dict(measure="../x"), "measure"),
        (dict(year=1899), "year"),
        (dict(year=10000), "year"),
        (dict(table="x\ny"), "table"),
        (dict(units=""), "units"),
        (dict(source_url="file:///tmp/x"), "source_url"),
        (dict(retrieved_on="yesterday"), "retrieved_on"),
        (dict(status="unknown"), "status"),
        (dict(value="NaN"), "value"),
        (dict(value=None), "published requires a value"),
        (dict(status="suppressed"), "suppressed/unavailable requires null"),
        (dict(status="unavailable"), "suppressed/unavailable requires null"),
        (dict(moe=1), "moe"),
    ],
)
def test_tax_rejects_invalid_cells(change: dict[str, object], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        TaxObservation.model_validate(tax() | change)


def test_crosswalk_keeps_both_denominators_and_chambers(tmp_path: Path) -> None:
    path = tmp_path / "crosswalk.json"
    path.write_text(json.dumps([crosswalk()]))
    row = read_crosswalk(path)[0]
    assert row.zcta_share == 0.2 and row.district_share == 0.1
    assert row.district.fact_key == "house:15:001:2022"
    assert row.zcta == "00123" and row.population_year == 2020
    assert CrosswalkRow.model_validate_json(row.model_dump_json()) == row
    assert (
        CrosswalkRow.model_validate(crosswalk() | dict(district=dict(chamber="senate", district=1)))
        != row
    )


@pytest.mark.parametrize(
    "change, error",
    [
        (dict(zcta="123"), "zcta"),
        (dict(zcta_population=0), "zcta_population"),
        (dict(district_population=0), "district_population"),
        (dict(intersection_population=-1), "intersection_population"),
        (dict(intersection_population=101), "intersection exceeds denominator"),
        (
            dict(zcta_population=300, intersection_population=201),
            "intersection exceeds denominator",
        ),
        (dict(population_year=2021), "population_year"),
        (dict(method="area-weighted"), "method"),
    ],
)
def test_crosswalk_rejects_invalid_weights(change: dict[str, object], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        CrosswalkRow.model_validate(crosswalk() | change)


@pytest.mark.parametrize(
    "reader, rows", [(read_tax, [tax(), tax()]), (read_crosswalk, [crosswalk(), crosswalk()])]
)
def test_readers_reject_duplicate_keys(
    reader: object, rows: list[dict[str, object]], tmp_path: Path
) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(rows))
    # Parametrization retains each reader's type at runtime.
    assert callable(reader)
    with pytest.raises(ValueError, match="duplicate"):
        reader(path)


def test_unmappable_zip_preserves_reason_without_inventing_geometry() -> None:
    row = UnmappableZIP.model_validate(dict(zip="00123", reason="no corresponding ZCTA"))
    assert row.zip == "00123" and row.reason == "no corresponding ZCTA"
    with pytest.raises(ValidationError, match="reason"):
        UnmappableZIP.model_validate(dict(zip="00123", reason=""))


def test_geometry_and_unmappable_readers(tmp_path: Path) -> None:
    from etl.zip_contract import ZctaGeometry, read_records

    geometry: dict[str, object] = dict(
        zcta="00123",
        vintage=2020,
        geometry=dict(type="Polygon", coordinates=[[[0, 0], [1, 0], [1, 1], [0, 0]]]),
        source_url="https://www.census.gov/example",
        retrieved_on="2026-10-29",
    )
    path = tmp_path / "geometry.json"
    path.write_text(json.dumps([geometry]))
    assert read_records(path, ZctaGeometry)[0].key == "00123"
    with pytest.raises(ValidationError, match="vintage"):
        ZctaGeometry.model_validate(geometry | dict(vintage=2022))
    path.write_text(json.dumps([dict(zip="00123", reason="no corresponding ZCTA")]))
    assert read_records(path, UnmappableZIP)[0].key == "00123"
