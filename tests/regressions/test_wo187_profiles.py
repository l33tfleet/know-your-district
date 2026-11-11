"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

from pathlib import Path
from typing import Any

import pytest

from etl.programs import Program
from tests.regressions.test_148_contracts import extended
from tests.regressions.test_148_profiles import DISTRICT, render
from tests.regressions.test_wo97_brief_page import Tree, build_db, row
from tests.regressions.test_wo122_browser_checks import base_url, browser, page

__all__ = [
    "DISTRICT",
    "Tree",
    "base_url",
    "browser",
    "build_db",
    "extended",
    "page",
    "render",
    "row",
]


# Replaces test_148_profiles.py::test_complete_render_uses_only_fact_evidence (wording only, #187).
def test_complete_render_uses_only_fact_evidence(
    extended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extended["enrichment"]["fact_references"][0]["geography"] = DISTRICT.fact_key
    extended["enrichment"]["stats"][0].update(
        value=987654321,
        moe=987654322,
        label="POISON_LABEL",
        source="POISON_SOURCE",
        method="POISON_METHOD",
        unit="POISON_UNIT",
        geography="POISON_GEOGRAPHY",
        table_id="POISON_TABLE",
        cell="POISON_CELL",
        vintage="POISON_VINTAGE",
        source_url="https://example.org/POISON_URL",
    )
    fact = row("population", DISTRICT.fact_key, 12345, 321).model_copy(
        update={"variable": "B22003_006E", "table_id": "B22003", "label": "Fact label"}
    )
    path = tmp_path / "facts.db"
    build_db(path, [fact])
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    html = render(Program.model_validate(extended), monkeypatch)
    tree = Tree()
    tree.feed(html)
    text = tree.root.text
    for expected in (
        "Fact label",
        "12,345",
        "321",
        "reliable",
        "margin of error (90%)",
        fact.source,
        fact.table_id,
        fact.vintage,
        fact.geography,
        fact.method,
        "Hawaiʻi",
        "People purchasing and preparing meals together",
        "Hawaiʻi HHS",
        "Monthly",
        "Agency household and income conditions apply",
        "The agency reviews exceptions",
        "2026-01-01",
        "2026-10-01",
        "2026-10-02",
        "Unknown",
        "2026-10-25",
        "Catalog maintainers",
        "2026-11-25",
        "Illustrative fixture",
        "CC-BY-4.0",
        "People in the area",
        "They do not estimate who is eligible or who is not taking part",
        "Aloha United Way 211",
    ):
        assert expected in text
    for poison in ("987654321", "987654322", "POISON_"):
        assert poison not in html
    assert tree.root.one("img").attrs["alt"] == "Coast"
    hrefs = [a.attrs["href"] for a in tree.root.find_all("a")]
    assert fact.endpoint in hrefs
    assert "https://creativecommons.org/licenses/by/4.0/" in hrefs
    assert "https://www.auw211.org/" in hrefs
