# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Programs that may help: each program's name, agency, purpose and official page, with the
line that the agency decides eligibility and a link to Aloha United Way 211.

The default catalog exposes wording and links only. The separate program_cards
flag adds strong, ranked district connections from the fact-reading match tool;
the catalog and its printable rendering remain available regardless of that flag."""

from functools import cache
from pathlib import Path

from app.features import enabled
from app.page_state import PageState
from etl.programs import load_catalog

CATALOG = Path(__file__).resolve().parents[2] / "data" / "programs.yaml"


@cache
def programs() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "name": p.name,
            "agency": p.agency,
            "purpose": p.purpose,
            "official_url": str(p.official_url),
            "guidance": p.guidance,
            "referral_url": p.referral_url,
        }
        for p in load_catalog(CATALOG)
    )


def context(state: PageState) -> dict[str, object]:
    result: dict[str, object] = {"programs": programs()}
    if enabled("program_cards", state):
        # Local: a catalog-only brief loads neither the cards nor the folder routes.
        from app.folders.routes import save_context
        from app.program_cards import load_cards

        result["program_cards"] = load_cards(state.district)
        result |= save_context(state, "program")
    return result
