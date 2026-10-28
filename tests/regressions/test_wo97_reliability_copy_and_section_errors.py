"""WO #97 review round: the reliability words are page wording, so they live in
`app/copy.yaml` (figures group) like every other string; and a section module whose
`context` is missing or not callable fails with a clear TypeError."""

import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import get_args

import pytest
import yaml
from fastapi.testclient import TestClient

import app.copy
from app.analysis.reliability import Reliability, classify
from app.brief import Section, render_context
from app.facts import acs_config
from app.main import app as asgi_app
from app.models import Fact
from app.page_state import PageState
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[2]
HOUSE_22 = "house:15:022:2022"
DETAILED = "https://api.census.gov/data/2024/acs/acs5"
PROFILE = "https://api.census.gov/data/2024/acs/acs5/profile"


def synthetic(variable: str, table_id: str, endpoint: str, value: float, moe: float) -> Fact:
    """A synthetic fact, never a published observation."""
    cv, reliability = classify(Decimal(repr(value)), Decimal(repr(moe)))
    return Fact(
        variable=variable,
        geography=HOUSE_22,
        vintage=acs_config()[0],
        value=value,
        moe=moe,
        cv=float(cv) if cv is not None else None,
        reliability=reliability,
        source="U.S. Census Bureau ACS 5-year (synthetic test row)",
        table_id=table_id,
        method="published estimate and 90% margin of error",
        endpoint=endpoint,
        label=f"Synthetic label for {variable}",
    )


# House 22 gets reliable, moderate and caution rows; every state row is absent (unavailable).
ROWS = [
    synthetic("B01003_001E", "B01003", DETAILED, 23456.0, 1234.0),
    synthetic("DP05_0024PE", "DP05", PROFILE, 21.3, 8.0),
    synthetic("B19013_001E", "B19013", DETAILED, 98765.0, 90000.0),
]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "facts.db"
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        columns = list(Fact.model_fields)
        db.executemany(
            f"INSERT INTO facts ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [tuple(getattr(r, c) for c in columns) for r in ROWS],
        )
    path.chmod(0o444)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return TestClient(asgi_app)


def test_fixture_rows_cover_every_flag_on_the_page() -> None:
    assert {r.reliability for r in ROWS} == {"reliable", "moderate", "caution"}


def test_copy_has_a_reliability_word_for_every_flag() -> None:
    copy = yaml.safe_load(app.copy.COPY_PATH.read_text())
    words = copy["sections"]["figures"]["reliability"]
    assert set(words) == set(get_args(Reliability))
    assert all(isinstance(w, str) and w.strip() for w in words.values())


@pytest.mark.parametrize("flag", get_args(Reliability))
def test_changing_reliability_copy_changes_the_page(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    copy = yaml.safe_load(app.copy.COPY_PATH.read_text())
    marker = f"Wo97 reliability marker {flag}"
    assert marker not in client.get("/brief/house/22").text
    copy["sections"]["figures"]["reliability"][flag] = marker
    edited = tmp_path / "copy.yaml"
    edited.write_text(yaml.safe_dump(copy, allow_unicode=True))
    monkeypatch.setattr(app.copy, "COPY_PATH", edited)
    html = client.get("/brief/house/22").text
    assert f'data-reliability="{flag}">{marker}</span>' in html


@pytest.fixture
def broken_section(request: pytest.FixtureRequest) -> Iterator[Section]:
    body: str = request.param
    module = ROOT / "app/sections/15_wo97_broken.py"
    assert not module.exists()
    module.write_text(f'"""Broken section added by a WO97 test."""\n\n{body}')
    try:
        yield Section("15", "wo97_broken")
    finally:
        module.unlink()


@pytest.mark.parametrize(
    "broken_section",
    ["MARKER = 1\n", 'context = "not callable"\n'],
    ids=["absent", "not-callable"],
    indirect=True,
)
def test_section_without_callable_context_raises_type_error(broken_section: Section) -> None:
    state = PageState(district=DistrictId(chamber="house", district=22))
    with pytest.raises(TypeError) as raised:
        render_context(broken_section, state)
    assert str(raised.value) == "app.sections.15_wo97_broken must define context(state)"
