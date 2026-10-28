# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Programs that may help: each program's name, agency, purpose and official page, with the
line that the agency decides eligibility and a link to Aloha United Way 211.

Only wording and links reach the template; the catalog's thresholds, proxies and dates do not,
so no catalog number can show on the page."""

from functools import cache
from pathlib import Path

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
    return {"programs": programs()}
