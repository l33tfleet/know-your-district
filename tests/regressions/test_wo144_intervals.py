"""WO144: one shared linear scale, with only published intervals drawn."""

from importlib import import_module  # noqa: F401  # pyright: ignore[reportUnusedImport] -- kept: #283 may delete only the superseded test
from pathlib import Path  # noqa: F401  # pyright: ignore[reportUnusedImport] -- kept: #283 may delete only the superseded test

import pytest
from fastapi.testclient import TestClient  # noqa: F401  # pyright: ignore[reportUnusedImport] -- kept: #283 may delete only the superseded test

from app.analysis.intervals import interval_layout
from app.counties import load_mapping  # noqa: F401  # pyright: ignore[reportUnusedImport] -- kept: #283 may delete only the superseded test
from app.main import app  # noqa: F401  # pyright: ignore[reportUnusedImport] -- kept: #283 may delete only the superseded test
from tests.regressions.test_wo97_brief_page import (
    build_db,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- #283 deletes only the superseded test
    parse,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- #283 deletes only the superseded test
    row,
)

GEOS = ("senate:15:007:2022", "county:15:009", "county:15:003", "state:15")


def test_proportional_offsets_and_widths() -> None:
    marks = interval_layout(
        [
            row("population", g, v, m)
            for g, v, m in zip(GEOS, (10, 30, 50, 90), (20, 10, 0, 10), strict=True)
        ]
    )
    a, b, c, d = marks
    assert [m.geography for m in marks] == list(GEOS)
    assert a.low == pytest.approx(0)  # negative endpoint is retained
    assert d.high == pytest.approx(100)
    assert (c.dot - a.dot) / (b.dot - a.dot) == pytest.approx(2)
    assert a.low is not None and a.high is not None
    assert b.low is not None and b.high is not None
    assert (a.high - a.low) / (b.high - b.low) == pytest.approx(2)
    assert c.low == c.dot == c.high  # published zero MOE is an interval


def test_missing_values_and_moes() -> None:
    marks = interval_layout(
        [None, row("population", GEOS[0], None, 500), row("population", GEOS[-1], 20, None)]
    )
    assert len(marks) == 1
    assert marks[0].dot == 100  # zero belongs to the domain even without an interval
    assert marks[0].low is None and marks[0].high is None
    assert interval_layout([None, row("population", GEOS[0], None, None)]) == []


def test_all_zero_values_have_finite_coordinates() -> None:
    marks = interval_layout(
        [row("population", g, 0, m) for g, m in zip(GEOS, (0, None, 0, None), strict=True)]
    )
    assert all(m.dot == 0 for m in marks)
    assert marks[0].low == marks[0].high == 0
    assert marks[1].low is None
