"""WO-47 boundary provenance requires an explicit ISO retrieval date."""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.boundaries import BoundaryCollection

FIXTURE = Path(__file__).parent / "fixtures" / "wo47_boundaries.geojson"


@pytest.mark.parametrize("retrieved_on", [0, 0.0, "0", "2026-10-25T00:00:00Z"])
def test_provenance_rejects_timestamp_instead_of_iso_date(retrieved_on: object) -> None:
    data = json.loads(FIXTURE.read_text())
    data["provenance"]["retrieved_on"] = retrieved_on
    with pytest.raises(ValidationError, match="retrieved_on"):
        BoundaryCollection.model_validate_json(json.dumps(data))


def test_provenance_accepts_iso_calendar_date() -> None:
    collection = BoundaryCollection.model_validate_json(FIXTURE.read_text())
    assert collection.provenance.retrieved_on == date(2026, 10, 25)
