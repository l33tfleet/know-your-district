# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Published SNAP outreach comparisons, shared unchanged by screen and print."""

from app import snap
from app.copy import section_copy
from app.features import load_features
from app.page_state import PageState

PRINT = True


def context(state: PageState) -> dict[str, object]:
    if not load_features().outreach:
        return {}
    result = snap.load_result(state.district)
    return {
        "result": result,
        # Keep the brief's neutral wording while preserving the canonical measure.
        "heading": result.heading.replace("below poverty", "in poverty"),
        "measure_note": result.measure_note.replace("below poverty", "under the poverty threshold"),
        "readings": (result.district, *result.counties, result.state),
        # Preserve the canonical caveat without the page's prohibited "eligible for" wording.
        "poverty_note": result.poverty_note.replace(
            "households eligible for SNAP but not enrolled",
            "unenrolled households that meet SNAP eligibility rules",
        ).replace(
            "not the higher Hawaiʻi HHS poverty guidelines",
            "not Hawaiʻi HHS poverty guidelines (which exceed Census thresholds)",
        ),
        "figures_copy": section_copy("figures"),
        "caption": "District, county and state published estimates",
        "estimate_label": "Estimate and uncertainty",
        "official_label": "Official SNAP program page",
        "referral_label": "Aloha United Way 211",
    }
