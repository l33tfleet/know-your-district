# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""A fixed SNAP question; its answer route (app/web/snap.py) fills the answer in by htmx.

Screen-only: the outreach card above already prints the same figures.
"""

from app.page_state import PageState
from app.tools.snap import Question

FEATURE = "snap_question"


def context(state: PageState) -> dict[str, object]:
    district = state.district
    hidden = {"question": Question.NO_SNAP_HOUSEHOLDS.value}
    if state.preview:
        hidden["preview"] = "1"
    if state.variant is not None:
        hidden["v"] = state.variant
    return {
        "action": f"/brief/{district.chamber}/{district.district}/snap-answer",
        "hidden": hidden,
    }
