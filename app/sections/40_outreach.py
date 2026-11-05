# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Published SNAP outreach comparisons, shared unchanged by screen and print."""

from app import snap
from app.copy import section_copy
from app.features import enabled, load_features
from app.page_state import PageState
from app.source_links import source_links

PRINT = True


def context(state: PageState) -> dict[str, object]:
    if not load_features().outreach:
        return {}
    result = snap.load_result(state.district)
    wording = snap.brief_wording()
    copy = section_copy("snap_question")
    readings = (result.district, *result.counties, result.state)
    checks_enabled = enabled("source_links", state)
    return {
        "result": result,
        "heading": wording.heading,
        "measure_note": wording.measure_note,
        "readings": readings,
        "source_links": {
            r.geography: source_links(r.fact)
            for r in readings
            if checks_enabled and r.fact is not None
        },
        "poverty_note": wording.poverty_note,
        "figures_copy": section_copy("figures"),
        "caption": copy["caption"],
        "estimate_label": copy["estimate_label"],
        "official_label": copy["official_label"],
        "referral_label": copy["referral_label"],
    }
