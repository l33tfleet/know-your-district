# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""The district's first outreach case, above the figures: who, why here, and the next step.

The figure is section 40's district reading, unchanged; this card adds no number.
"""

from app import snap
from app.cases import PROBLEMS, case
from app.copy import section_copy
from app.features import load_features
from app.page_state import PageState

PRINT = True
CASE_ID = "snap_poverty_no_receipt"


def context(state: PageState) -> dict[str, object]:
    if not load_features().outreach:
        return {}
    record = case(CASE_ID)
    result = snap.load_result(state.district)
    reading = result.district
    copy = section_copy("case")
    fact = reading.fact
    available = fact is not None and fact.value is not None
    steps = [(step.label, str(step.url)) for step in record.action.steps]
    if result.referral is not None:
        steps.insert(1, (copy["outreach_label"], str(result.referral.outreach_url)))
    return {
        "case": record,
        "title": f"{copy['population']} · {record.program.name}",
        "reading": reading if available else None,
        # The estimation method only; its retrieval details stay in section 40's citation.
        "citation": copy["citation"].format(
            source=fact.source,
            table_id=fact.table_id,
            vintage=fact.vintage,
            geography=reading.geography_name,
            method=fact.method.split(";")[0],
        )
        if fact is not None
        else None,
        "why": copy["why"].format(units=reading.units.capitalize()),
        "evidence": [
            (copy["problems"][p], copy["known"], record.known[p])
            if p in record.known
            else (copy["problems"][p], copy["unknown"], record.unknown[p])
            for p in PROBLEMS
        ],
        "gap": copy["gaps"][record.failure.kind],
        "action": copy["actions"][record.action.kind],
        "steps": steps,
    }
