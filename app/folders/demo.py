"""Preview/refresh the immutable seed: python -m app.folders.demo [--matches] [--commit].
Uses KYD_FOLDERS_DB (or the store's XDG default), with the folders flag on.
Without --matches it seeds catalog cases (#287 supplies remaining cases); with it, three House 22
matches from the matching tool, with accepted decisions. Scheduling belongs to #234.
Preview reads only the catalog and the tool, never the store."""

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from app.cases import load_cases
from app.folders.references import encode_match
from app.folders.store import (
    DEMO_ID,
    DemoCard,
    DemoMatch,
    FolderStore,
    Priority,
    Status,
    default_path,
)
from app.page_state import page_state
from etl.boundaries import DistrictId

DISTRICT = DistrictId(chamber="house", district=22)
PRIORITIES: tuple[Priority, ...] = ("high", "normal", "low")
STATUSES: tuple[Status, ...] = ("idea", "contacted", "planned")
# Outreach steps only: no observation about any resident, never a claim that anyone qualifies.
MATCH_NOTES = (
    (
        "2026-10-20",
        "Demo outreach idea: ask community navigators which official program"
        " materials they share; refer questions to the agency and Aloha United Way 211.",
    ),
    (
        "2026-10-27",
        "Demo outreach contact: sent the official program page to a community"
        " partner; the agency decides eligibility, and Aloha United Way 211 answers questions.",
    ),
    (
        "2026-11-03",
        "Demo outreach plan: table at a district event with the official program"
        " page and Aloha United Way 211 referral cards.",
    ),
)


def plan() -> tuple[DemoCard, ...]:
    return tuple(
        DemoCard(
            case_id=case.id,
            priority=priority,
            status=status,
            dated="2026-10-20",
            body="Demo outreach planning: review agency materials with community navigators.",
        )
        for case, priority, status in zip(load_cases().cases, PRIORITIES, STATUSES, strict=False)
    )


def match_plan() -> tuple[DemoMatch, ...]:
    """The tool's first three House 22 matches, resolved afresh; any further ones stay pending."""
    # Local: program cards load the cases, which `validate_startup` loads first.
    from app.tools.matches import find_matches, resolve_matches
    from app.tools.suggestions import propose

    chosen = find_matches(DISTRICT)[: len(MATCH_NOTES)]
    if len(chosen) < len(MATCH_NOTES):
        raise ValueError(f"House 22 offers {len(chosen)} matches; the demo needs three")
    resolve_matches(DISTRICT, chosen)  # refuses an identity the tool no longer offers
    proposals = {p.match: p for p in propose(DISTRICT)}
    return tuple(
        DemoMatch(
            match=match,
            source=proposals[match].source,
            checked=proposals[match].dated,
            priority=priority,
            status=status,
            dated=dated,
            body=body,
        )
        for match, priority, status, (dated, body) in zip(
            chosen, PRIORITIES, STATUSES, MATCH_NOTES, strict=True
        )
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Atomically refresh only the seed")
    parser.add_argument(
        "--matches", action="store_true", help="Seed three House 22 match cards with decisions"
    )
    args = parser.parse_args(argv)
    # The CLI needs the same declarations as web startup before validating feature policy.
    from app.main import validate_startup

    validate_startup()
    matches = match_plan() if args.matches else ()
    cards = () if args.matches else plan()
    if args.matches:
        print(f"Refresh /f/{DEMO_ID}: " + ", ".join(encode_match(m.match) for m in matches))
    else:
        print(f"Refresh /f/{DEMO_ID}: " + ", ".join(c.case_id for c in cards))
        if len(cards) < 3:
            print("Three-case production fixture awaits #287; only catalog cases are included.")
    if not args.commit:
        print("Preview only. Run with --commit to refresh the seed.")
        return
    state = page_state("house", "22")
    assert state is not None
    configured = os.environ.get("KYD_FOLDERS_DB")
    folders = FolderStore(Path(configured) if configured else default_path(), state)
    if args.matches:
        folders.refresh_demo_matches(matches)
    else:
        folders.refresh_demo(cards)


if __name__ == "__main__":
    main()
