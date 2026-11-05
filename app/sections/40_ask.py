# ruff: noqa: N999 -- sections use the NN_name.py discovery convention
"""Screen-only Ask form; all answers come through the gated POST boundary."""

from urllib.parse import urlencode

from app.page_state import PageState

FEATURE = "ask"
PRINT = False


def context(state: PageState) -> dict[str, object]:
    query: dict[str, str] = {}
    if state.preview:
        query["preview"] = "1"
    if state.variant is not None:
        query["v"] = state.variant
    district = state.district
    action = f"/brief/{district.chamber}/{district.district}/ask"
    if query:
        action += "?" + urlencode(query)
    return {"action": action}
