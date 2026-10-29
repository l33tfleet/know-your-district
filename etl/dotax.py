"""Offline DOTAX A-14/A-16 XLSX facade returning validated ZIP tax contracts.

Layout recorded from 2023indinc_tables.xlsx (2026-10-29). Validate headers
before assigning meaning to coordinates; never infer federal AGI from A-14.
Only published cells are read, with no formula evaluation or output writes.
"""

import posixpath
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from etl.zip_contract import TaxObservation

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_A14 = {
    "C": ("returns", "returns"),
    "F": ("hawaii_agi", "million USD"),
    "H": ("median_hawaii_agi", "USD"),
    "K": ("tax_before_credits", "million USD"),
    "M": ("median_tax_before_credits", "USD"),
    "O": ("tax_after_credits", "million USD"),
    "Q": ("median_tax_after_credits", "USD"),
    "T": ("positive_tax_before_credits", "fraction"),
    "V": ("positive_tax_after_credits", "fraction"),
}
_HEADERS14 = {
    "C3": "Number of Returns",
    "F3": "Hawai'i AGI*",
    "K3": "Tax Liability",
    "T3": "% of Returns with (+) Tax Liability",
    "F4": "Amount (Million $)",
    "H4": "Median ($)",
    "K4": "Before Credits",
    "O4": "After Credits*",
    "K5": "Amount (Million $)",
    "M5": "Median ($)",
    "O5": "Amount (Million $)",
    "Q5": "Median ($)",
    "T5": "Before Credits",
    "V5": "After Credits",
}


def _text(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t", "n")
    if cell.find(f"{_NS}f") is not None:
        raise ValueError("formula cells are not published values")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{_NS}t")).strip()
    value = cell.findtext(f"{_NS}v", "").strip()
    if kind == "s":
        return strings[int(value)].strip()
    if kind not in ("n", "str"):
        raise ValueError(f"unsupported cell type: {kind}")
    return value


def _columns(cells: dict[str, str], table: str) -> list[tuple[str, str, str, str, int]]:
    headers = {"A3": "ZIP CODE", "B3": "GEOGRAPHIC AREA"}
    columns: list[tuple[str, str, str, str, int]]
    title = cells.get("A2", "")
    if table == "A-14":
        match = re.fullmatch(
            r"SELECTED DATA FROM RESIDENT TAX RETURNS BY ZIP CODE [–-] ([0-9]{4})", title
        )
        if match is None:
            raise ValueError("A-14 title/year header changed")
        years = [int(match[1])]
        headers.update(_HEADERS14)
        columns = [(col, measure, units, "all", years[0]) for col, (measure, units) in _A14.items()]
    else:
        match = re.fullmatch(
            r"MEDIAN FEDERAL ADJUSTED GROSS INCOME \(AGI\) OF RESIDENTS BY FILING STATUS "
            r"AND ZIP CODE (?:[–-]|IN) ([0-9]{4}) VERSUS ([0-9]{4})",
            title,
        )
        if match is None:
            raise ValueError("A-16 title/year header changed")
        years = [int(match[1]), int(match[2])]
        if years[0] == years[1] or [cells.get("C3"), cells.get("P3")] != list(map(str, years)):
            raise ValueError("A-16 years disagree with title")
        columns = []
        for year, groups in zip(
            years, (("C", "E", "G", "I", "K", "M"), ("P", "R", "T", "V", "X", "Z")), strict=True
        ):
            for status, number, median in zip(
                ("all", "joint", "other"), groups[::2], groups[1::2], strict=True
            ):
                headers[number + "4"] = f"Filing Status: {status.title()}"
                headers[number + "5"] = "Number"
                headers[median + "5"] = "Median"
                columns.extend(
                    (
                        (number, "federal_agi_returns", "returns", status, year),
                        (median, "median_federal_agi", "USD", status, year),
                    )
                )
    if any(cells.get(key) != value for key, value in headers.items()):
        raise ValueError(f"{table} header layout or units changed")
    return columns


def read_workbook(path: Path, *, source_url: str, retrieved_on: date) -> list[TaxObservation]:
    """Parse all A14/A16 continuation sheets; preserve source units and tax years.

    Excel percentage cells contain fractions, kept as fractions rather than
    relabeled percents. A-16 medians are dollars; its Number columns are returns.
    The caller supplies the exact downloaded URL and retrieval date, not a vintage.
    """
    records: list[TaxObservation] = []
    tables: set[str] = set()
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(t.text or "" for t in item.iter(f"{_NS}t"))
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        targets = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in workbook.findall(f"{_NS}sheets/{_NS}sheet"):
            if not re.fullmatch(r"A(?:14|16)(?:-[0-9]+)?", sheet.attrib["name"]):
                continue
            target = targets[sheet.attrib[f"{_REL}id"]]
            member = posixpath.normpath(posixpath.join("xl", target)).lstrip("/")
            cells = {
                c.attrib["r"]: _text(c, strings)
                for c in ET.fromstring(archive.read(member)).iter(f"{_NS}c")
            }
            table = "A-14" if sheet.attrib["name"].startswith("A14") else "A-16"
            if cells.get("A1") not in (f"TABLE {table}", f"TABLE {table} (CONTINUED)"):
                raise ValueError("sheet table identity changed")
            tables.add(table)
            columns = _columns(cells, table)
            for address, code in cells.items():
                if not re.fullmatch(r"A[0-9]+", address) or int(address[1:]) <= 5 or not code:
                    continue
                # Footnotes are not ZIP rows; populated geographic rows must be valid ZIPs.
                row = address[1:]
                if not cells.get("B" + row):
                    continue
                if not re.fullmatch(r"[0-9]{5}", code):
                    raise ValueError(f"invalid ZIP: {code}")
                for col, measure, units, filing_status, year in columns:
                    raw = cells.get(col + row, "")
                    status = (
                        "suppressed" if raw == "s" else "unavailable" if not raw else "published"
                    )
                    try:
                        value = Decimal(raw) if status == "published" else None
                    except InvalidOperation as exc:
                        raise ValueError(f"invalid numeric cell {col}{row}: {raw}") from exc
                    records.append(
                        TaxObservation.model_validate(
                            dict(
                                zip=code,
                                measure=measure,
                                filing_status=filing_status,
                                year=year,
                                units=units,
                                value=value,
                                status=status,
                                table=table,
                                source_url=source_url,
                                retrieved_on=retrieved_on,
                            )
                        )
                    )
    if tables != {"A-14", "A-16"}:
        raise ValueError("workbook requires tables A-14 and A-16")
    if len({record.key for record in records}) != len(records):
        raise ValueError("duplicate tax observation key")
    return records
