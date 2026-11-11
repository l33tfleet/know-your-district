"""Preview/refresh the immutable seed: python -m app.folders.demo [--matches] [--commit].
Uses KYD_FOLDERS_DB (or the store's XDG default), with the folders flag on.
#287 supplies remaining cases; scheduling belongs to #234. Preview reads only catalog.
--matches seeds the tool's first three House 22 matches as accepted; the rest stay pending."""

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

# Outreach steps only: no observation about any resident, never a claim that anyone qualifies.
REFERRAL = " The agency decides eligibility; Aloha United Way 211 answers questions."
MATCH_NOTES: tuple[tuple[Priority, Status, str, str], ...] = (
    ("high", "idea", "2026-10-20", "Demo outreach idea: ask navigators for official materials."),
    (
        "normal",
        "contacted",
        "2026-10-27",
        "Demo outreach contact: sent a partner the program page.",
    ),
    ("low", "planned", "2026-11-03", "Demo outreach plan: table at a district event."),
)


def plan() -> tuple[DemoCard, ...]:
    priorities: tuple[Priority, ...] = ("high", "normal", "low")
    statuses: tuple[Status, ...] = ("idea", "contacted", "planned")
    return tuple(
        DemoCard(
            case_id=case.id,
            priority=priority,
            status=status,
            dated="2026-10-20",
            body="Demo outreach planning: review agency materials with community navigators.",
        )
        for case, priority, status in zip(load_cases().cases, priorities, statuses, strict=False)
    )


def match_plan() -> tuple[DemoMatch, ...]:
    """The tool's first three House 22 matches, resolved afresh; any further ones stay pending."""
    # Local: program cards load the cases, which `validate_startup` loads first.
    from app.tools.matches import find_matches, resolve_matches
    from app.tools.suggestions import propose

    district = DistrictId(chamber="house", district=22)
    chosen = find_matches(district)[:3]
    if len(chosen) < 3:
        raise ValueError(f"House 22 offers {len(chosen)} matches; the demo needs three")
    resolve_matches(district, chosen)  # refuses an identity the tool no longer offers
    offered = {p.match: p for p in propose(district)}
    return tuple(
        DemoMatch(
            match=match,
            source=offered[match].source,
            checked=offered[match].dated,
            priority=priority,
            status=status,
            dated=dated,
            body=body + REFERRAL,
        )
        for match, (priority, status, dated, body) in zip(chosen, MATCH_NOTES, strict=True)
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Atomically refresh only the seed")
    parser.add_argument("--matches", action="store_true", help="Seed three House 22 matches")
    args = parser.parse_args(argv)
    # The CLI needs the same declarations as web startup before validating feature policy.
    from app.main import validate_startup

    validate_startup()
    matches = match_plan() if args.matches else None
    cards = () if matches else plan()
    keys = [encode_match(m.match) for m in matches] if matches else [c.case_id for c in cards]
    print(f"Refresh /f/{DEMO_ID}: " + ", ".join(keys))
    if not matches and len(cards) < 3:
        print("Three-case production fixture awaits #287; only catalog cases are included.")
    if not args.commit:
        print("Preview only. Run with --commit to refresh the seed.")
        return
    state = page_state("house", "22")
    assert state is not None
    configured = os.environ.get("KYD_FOLDERS_DB")
    folders = FolderStore(Path(configured) if configured else default_path(), state)
    if matches:
        folders.refresh_demo_matches(matches)
    else:
        folders.refresh_demo(cards)


if __name__ == "__main__":
    main()
