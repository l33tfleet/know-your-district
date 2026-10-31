# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""The opening outreach case: who may benefit, why this district, the next useful step.

Reads the same SNAP result as section 40, which stays as the evidence. No new number,
no arithmetic, no model call.
"""

from markupsafe import Markup

from app import snap
from app.cases import PROBLEMS, case
from app.copy import section_copy
from app.features import enabled, load_features
from app.folders.store import FEATURE as FOLDERS
from app.page_state import PageState

PRINT = True
CASE_ID = "snap_no_receipt"


def case_card(state: PageState, case_id: str) -> dict[str, object]:
    """One case for one district, read fresh; the brief and a saved folder both render this."""
    # Mirrors section 40: the same flag hides both, before anything loads.
    if not load_features().outreach:
        return {}
    record = case(case_id)
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
        "heading_id": "case-heading",
        "evidence_href": "#outreach-heading",
    }


def save_control(state: PageState, case_id: str) -> Markup:
    """The brief's form that starts a folder; the form carries only the case and its district."""
    district = state.district
    return Markup(
        '<form method="post" action="/folders{query}">'
        '<input type="hidden" name="case_id" value="{case_id}">'
        '<input type="hidden" name="chamber" value="{chamber}">'
        '<input type="hidden" name="district" value="{district}">'
        '<button type="submit">{label}</button></form>'
    ).format(
        query="?preview=1" if state.preview else "",
        case_id=case_id,
        chamber=district.chamber,
        district=district.district,
        label=section_copy("case")["save_label"],
    )


def context(state: PageState) -> dict[str, object]:
    card = case_card(state, CASE_ID)
    if card and enabled(FOLDERS, state):
        card["save_control"] = save_control(state, CASE_ID)
    return card
