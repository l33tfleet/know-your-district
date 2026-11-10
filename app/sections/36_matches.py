# ruff: noqa: N999 -- sections use the NN_name.py discovery convention
"""Inspectable population/program connections, with the evidence ceiling visible.

Use the canonical population registry and mapping contracts. Missing facts remain
unavailable; neither review status nor a survey count establishes eligibility.
"""

from app.folders.routes import save_context
from app.match_cards import to_match_card
from app.page_state import PageState
from app.tools.matches import DistrictMatches
from etl.programs.mappings import load_mappings

# The expanded evidence belongs on screen to preserve the one-page print brief.
FEATURE = "matches"
PRINT = False
# Keep the existing section wording contract; templates contain no literal prose.
WORDS = {
    "heading": "Groups ranked for outreach, with programs that may help",
    "band": "Outreach band:",
    "reason": "Ranking reason and calculations",
    "preview": "Preview: expert review is pending. Bands rank groups to reach in this district. They are not the odds that a person meets the rules. Weak evidence is not the same as too little evidence.",
    "intro": "This list helps plan outreach. A survey group does not show that a person can get help. It does not show a gap in sign-ups.",
    "review": "Program-expert review:",
    "survey": "Survey population:",
    "summary": "Measure, conditions and evidence",
    "source": "Source",
    "published": "published for district,",
    "plan": "plan.",
    "universe": "Universe",
    "exclusions": "Exclusions",
    "numerator": "Numerator measures",
    "denominator": "Denominator measures",
    "period": "Reference period",
    "method": "Method",
    "missing": "Missing measurements",
    "missing_note": "No eligibility or nonparticipation count is available from these measurements.",
    "input": "Published input",
    "table": "table",
    "endpoint": "Source endpoint",
    "observed": "Observed conditions",
    "unobserved": "Unobserved conditions",
    "none": "None documented.",
    "official": "Official program information",
    "referral": "Aloha United Way 211",
}


def context(state: PageState) -> dict[str, object]:
    ranked = DistrictMatches(state.district).get_matches(load_mappings())
    cards = [to_match_card(match) for match in ranked]
    return {"matches": cards, "words": WORDS} | save_context(state, "ranked")
