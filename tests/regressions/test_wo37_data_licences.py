"""WO #37: every specified ACS product has terms and an attribution line."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("product", ["Detailed Tables", "Data Profiles", "Subject Tables"])
def test_acs_product_has_licence_and_attribution(product: str) -> None:
    data_doc = (ROOT / "docs/data.md").read_text(encoding="utf-8")
    licences = data_doc.split("## Data licences\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in licences.splitlines() if line.startswith("| ACS ")]
    matching_rows = [row for row in rows if product in row.split("|")[1]]
    assert len(matching_rows) == 1, f"Missing or duplicate licence entry for {product}"
    cells = [cell.strip() for cell in matching_rows[0].strip("|").split("|")]
    assert len(cells) == 4
    dataset, publisher, terms, attribution = cells
    assert "2020–2024" in dataset
    assert publisher == "U.S. Census Bureau"
    assert "public domain" in terms
    assert "Source: U.S. Census Bureau" in attribution
    assert product in attribution
    assert "2020–2024" in attribution
    assert "[table ID and title]" in attribution
    assert "[geography]" in attribution
    assert "accessed [date]" in attribution
