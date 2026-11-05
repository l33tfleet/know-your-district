"""District-bound SNAP answer for the fixed question; reads the outreach card's result, no model.

The brief wording comes from app.snap.brief_wording so the answer and the card say the
same thing; tests/regressions/test_wo136_answer.py pins that they match.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app import snap
from app.snap import Reading, SnapResult
from etl.boundaries import DistrictId


class Question(StrEnum):
    NO_SNAP_HOUSEHOLDS = "no_snap_households"


class SnapAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: SnapResult
    heading: str
    measure_note: str
    poverty_note: str
    readings: tuple[Reading, ...]


class DistrictSnap:
    """Bind once to the request's validated district, never to user-supplied scope."""

    def __init__(self, district: DistrictId) -> None:
        self._district = district

    def answer(self) -> SnapAnswer:
        """The published joint cell for the district, its counties and the state.

        Each Reading keeps the original Fact with its citation and uncertainty.
        """
        result = snap.load_result(self._district)
        wording = snap.brief_wording()
        return SnapAnswer(
            result=result,
            heading=wording.heading,
            measure_note=wording.measure_note,
            poverty_note=wording.poverty_note,
            readings=(result.district, *result.counties, result.state),
        )
