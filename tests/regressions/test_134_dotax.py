"""Recorded DOTAX 2023 headers with synthetic cells, not published observations.

Fixture source: https://files.hawaii.gov/tax/stats/stats/indinc/2023indinc_tables.xlsx
Retrieved 2026-10-29. A-14 uses million dollars/dollars/fractions; A-16 has
2023 and 2022, All/Joint/Other, and federal (not Hawaiʻi) AGI.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest

from etl.dotax import read_workbook
from etl.zip_contract import TaxObservation

FIXTURE = Path(__file__).parent / "fixtures/134_dotax.xlsx"
URL = "https://files.hawaii.gov/tax/stats/stats/indinc/2023indinc_tables.xlsx"
DATE = date(2026, 10, 29)


def read(path: Path = FIXTURE) -> list[TaxObservation]:
    return read_workbook(path, source_url=URL, retrieved_on=DATE)


def test_recorded_workbook_preserves_units_years_and_suppression() -> None:
    records = read()
    assert len(records) == 42
    assert len({row.key for row in records}) == len(records)
    assert {row.zip for row in records} == {"00123", "96742"}
    assert {row.year for row in records} == {2022, 2023}
    assert all(str(row.source_url) == URL and row.retrieved_on == DATE for row in records)
    indexed = {
        (r.table, r.measure, r.filing_status, r.year): r for r in records if r.zip == "00123"
    }

    def cell(table: str, measure: str, status: str = "all", year: int = 2023) -> TaxObservation:
        return indexed[table, measure, status, year]

    assert cell("A-14", "returns").value == Decimal(0)
    assert cell("A-14", "returns").status == "published"
    assert cell("A-14", "returns").units == "returns"
    agi = cell("A-14", "hawaii_agi")
    assert (agi.value, agi.units) == (Decimal("-1.25"), "million USD")
    suppressed = cell("A-14", "median_hawaii_agi")
    assert (suppressed.value, suppressed.status) == (None, "suppressed")
    blank = cell("A-14", "tax_before_credits")
    assert (blank.value, blank.status) == (None, "unavailable")
    share = cell("A-14", "positive_tax_before_credits")
    assert (share.value, share.units) == (Decimal("0.75"), "fraction")
    median = cell("A-16", "median_federal_agi")
    assert (median.value, median.units) == (Decimal("123.45"), "USD")
    assert cell("A-16", "median_federal_agi", year=2022).value == Decimal("100.5")
    assert cell("A-16", "federal_agi_returns", "joint").status == "suppressed"
    assert cell("A-16", "median_federal_agi", "joint").value is None
    assert cell("A-16", "federal_agi_returns", "other").status == "unavailable"
    assert cell("A-16", "federal_agi_returns", "joint", 2022).value == Decimal(2)


def altered(tmp_path: Path, old: bytes, new: bytes, sheet: int = 1) -> Path:
    path = tmp_path / "altered.xlsx"
    with ZipFile(FIXTURE) as source, ZipFile(path, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == f"xl/worksheets/sheet{sheet}.xml":
                assert old in data
                data = data.replace(old, new)
            target.writestr(name, data)
    return path


@pytest.mark.parametrize(
    "old,new,sheet,error",
    [
        (b"Amount (Million $)", b"Amount (Thousand $)", 1, "header"),
        (b"Filing Status: Other", b"Filing Status: Single", 3, "header"),
        (b">2022<", b">2021<", 3, "years"),
        (b"SELECTED DATA", b"UNEXPECTED DATA", 1, "title/year"),
        (b"MEDIAN FEDERAL", b"MEDIAN HAWAII", 3, "title/year"),
        (b">-1.25<", b">NaN<", 1, "value"),
        (b">-1.25<", b">unknown<", 1, "numeric cell"),
        (b't="n"><v>-1.25', b't="e"><v>-1.25', 1, "cell type"),
        (b"<v>-1.25</v>", b"<f>1+1</f><v>-1.25</v>", 1, "formula"),
        (b">96742<", b">00123<", 2, "duplicate"),
        (b">00123<", b">123<", 1, "ZIP"),
        (b"TABLE A-14", b"TABLE A-99", 1, "table"),
    ],
)
def test_workbook_rejects_ambiguous_inputs(
    tmp_path: Path, old: bytes, new: bytes, sheet: int, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        read(altered(tmp_path, old, new, sheet))


def test_workbook_requires_both_tables(tmp_path: Path) -> None:
    path = tmp_path / "missing.xlsx"
    with ZipFile(FIXTURE) as source, ZipFile(path, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/workbook.xml":
                data = data.replace(b"A16-", b"Unrelated-")
            target.writestr(name, data)
    with pytest.raises(ValueError, match="requires tables A-14 and A-16"):
        read(path)


def test_workbook_rejects_equal_comparison_years(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="years disagree"):
        read(altered(tmp_path, b"2022", b"2023", 3))


def test_shared_strings_and_numeric_zip_encoding(tmp_path: Path) -> None:
    path = tmp_path / "shared.xlsx"
    with ZipFile(FIXTURE) as source, ZipFile(path, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(
                    b'<c r="H7" t="inlineStr"><is><t>s</t></is></c>',
                    b'<c r="H7" t="s"><v>0</v></c>',
                )
            if name == "xl/worksheets/sheet2.xml":
                data = data.replace(
                    b'<c r="A7" t="inlineStr"><is><t>96742</t></is></c>',
                    b'<c r="A7"><v>96742</v></c>',
                )
            target.writestr(name, data)
        target.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>s</t></si></sst>",
        )
    assert read(path) == read()
