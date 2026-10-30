# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""The opening outreach case: who may benefit, why this district, the next useful step.

Reads the same SNAP result as section 40, which stays as the evidence. No new number,
no arithmetic, no model call.
"""

from app import snap
from app.cases import PROBLEMS, case
from app.copy import section_copy
from app.features import load_features
from app.page_state import PageState

PRINT = True
CASE_ID = "snap_no_receipt"


def context(state: PageState) -> dict[str, object]:
    # Mirrors section 40: the same flag hides both, before anything loads.
    if not load_features().outreach:
        return {}
    record = case(CASE_ID)
    result = snap.load_result(state.district)
    reading = result.district
    copy = section_copy("case")
    fact = reading.fact
    citation = None
    if fact is not None and fact.value is not None:
        citation = copy["citation"].format(
            source=fact.source,
            table_id=fact.table_id,
            vintage=fact.vintage,
            geography=fact.geography,
            method=fact.method,
        )
    outreach = result.referral.outreach_url if result.referral is not None else None
    links = [
        (copy["official_label"], str(record.program.url)),
        *([(copy["outreach_label"], str(outreach))] if outreach is not None else []),
        *((link.label, str(link.url)) for link in record.action.links),
    ]
    return {
        "result": result,
        "reading": reading,
        "record": record,
        "citation": citation,
        "unavailable": copy["unavailable"].format(district=reading.geography_name),
        # Section 40's heading, with its neutral wording.
        "title": copy["title"].format(
            population=result.heading.replace("below poverty", "in poverty"),
            program=record.program.name,
        ),
        "known": [(copy["problems"][p], record.known[p]) for p in PROBLEMS if p in record.known],
        "unknown": [
            (copy["problems"][p], record.unknown[p]) for p in PROBLEMS if p in record.unknown
        ],
        "gap": copy["gaps"][record.failure.gap],
        "action": copy["actions"][record.action.kind],
        "checked": copy["rule_checked"].format(date=record.program.rule_checked.isoformat()),
        "links": links,
    }
