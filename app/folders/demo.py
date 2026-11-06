"""Preview/refresh the immutable public seed: python -m app.folders.demo [--commit].

Uses KYD_FOLDERS_DB (or the store's XDG default), with the folders flag on.
Preview reads only the catalog. #287 supplies the remaining production research cases;
no placeholder programs, duplicated district cases, or invented actions stand in for them.
Scheduling belongs to #234. Refresh uses the existing schema; no migration is needed.
"""

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from app.cases import load_cases
from app.folders.store import DEMO_ID, DemoCard, FolderStore, Priority, Status, default_path
from app.page_state import page_state


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


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Atomically refresh only the seed")
    args = parser.parse_args(argv)
    # The CLI needs the same declarations as web startup before validating feature policy.
    from app.main import validate_startup

    validate_startup()
    cards = plan()
    print(f"Refresh /f/{DEMO_ID}: " + ", ".join(c.case_id for c in cards))
    if len(cards) < 3:
        print("Three-case production fixture awaits #287; only catalog cases are included.")
    if not args.commit:
        print("Preview only. Run with --commit to refresh the seed.")
        return
    state = page_state("house", "22")
    assert state is not None
    configured = os.environ.get("KYD_FOLDERS_DB")
    FolderStore(Path(configured) if configured else default_path(), state).refresh_demo(cards)


if __name__ == "__main__":
    main()
