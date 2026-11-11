"""WO260: the state's B01003 total population reads as a controlled total, never caution.

Kept apart from `test_wo260_controlled_totals.py` and importing only names that exist
before WO260, so on the old code this test fails on its assertions, not at import.
The wording is spelled out literally (app/copy.yaml, figures: controlled_total,
controlled, controlled_moe) for the same reason.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.reliability import FLAG_WORDS
from app.main import app
from app.models import Fact
from tests.regressions.test_wo97_brief_page import ROWS, STATE, brief, build_db, row
from tests.regressions.test_wo261_figure_sentences import COUNTY_ROWS, sentence

CAUTION = FLAG_WORDS["caution"]
CONTROLLED_METHOD = (
    "published estimate and 90% margin of error. MOE controlled. MOE annotation: *****"
)
STATE_TOTAL: Fact = row("population", STATE, 1446146.0, None).model_copy(
    update={"method": CONTROLLED_METHOD}
)
FIXTURE = [
    STATE_TOTAL if (r.variable, r.geography) == ("B01003_001E", STATE) else r for r in ROWS
] + list(COUNTY_ROWS)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "facts.db"
    build_db(path, FIXTURE)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return TestClient(app)


@pytest.mark.parametrize("path", ["/brief/house/22", "/brief/senate/5"])
def test_state_b01003_total_reads_controlled_total(client: TestClient, path: str) -> None:
    node = brief(client, path).one("div", class_="figure", data_figure="population")
    state = sentence(node).one("span", class_="reading", data_geography=STATE)
    assert state.one(class_="reliability").text == "no sampling error"
    assert state.one("span", class_="moe").text == "controlled total"
    assert CAUTION not in state.text
    dl = node.one("dl", data_geography=STATE)
    assert dl.one(data_field="table_id").text == "B01003"
    assert dl.one(data_field="moe").text == (
        "None. This is a controlled total, with no sampling error."
    )
    assert CAUTION not in dl.text
