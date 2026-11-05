"""District-bound SNAP answer for the fixed question; reads the outreach card's result, no model.

The brief wording mirrors app/sections/40_outreach.py so the answer and the card say the
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
        return SnapAnswer(
            result=result,
            heading=result.heading.replace("below poverty", "in poverty"),
            measure_note=result.measure_note.replace(
                "below poverty", "under the poverty threshold"
            ),
            poverty_note=result.poverty_note.replace(
                "households eligible for SNAP but not enrolled",
                "unenrolled households that meet SNAP eligibility rules",
            ).replace(
                "not the higher Hawaiʻi HHS poverty guidelines",
                "not Hawaiʻi HHS poverty guidelines (which exceed Census thresholds)",
            ),
            readings=(result.district, *result.counties, result.state),
        )
