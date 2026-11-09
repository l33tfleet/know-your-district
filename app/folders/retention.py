"""How long a folder lives, the cleanup that removes it, and the schedule that runs it.

A folder expires 180 days after its last write. The store refuses an expired folder from that
moment, so a late cleanup never extends its life. Cleanup needs the `folders` flag on, like every
other write to the store.

`app/main.py` runs `scheduled_cleanup` once at startup, before serving, then `run_cleanups`
repeats it every `CLEANUP_INTERVAL_SECONDS` (a day) until shutdown. A scheduled pass skips while
the flag is off and before the file exists (it only removes rows, so it never creates the file);
a store that cannot be opened is logged as an error and the site keeps serving, as the folder
routes answer 503 for the same fault.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NoReturn

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.folders.store import FolderStore

RETENTION = timedelta(days=180)
CLEANUP_INTERVAL_SECONDS = timedelta(days=1).total_seconds()
log = logging.getLogger(__name__)


class Purged(BaseModel):
    """Rows removed directly; a removed folder's cards and notes go with it, uncounted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    folders: int
    cards: int
    notes: int
    rate_buckets: int


def expiry_cutoff(stamp: str) -> str:
    """A row last changed at or before this moment has expired, as of `stamp`."""
    return (datetime.fromisoformat(stamp) - RETENTION).isoformat(timespec="seconds")


def cleanup(store: "FolderStore", *, dry_run: bool = False) -> Purged:
    """Remove what has expired; `dry_run` reports the same counts and removes nothing."""
    start = time.perf_counter()
    purged = store.purge_expired(dry_run=dry_run)
    log.info(
        "folder cleanup%s: %d folders, %d cards, %d notes, %d rate buckets in %.1f ms",
        " (dry run)" if dry_run else "",
        purged.folders,
        purged.cards,
        purged.notes,
        purged.rate_buckets,
        (time.perf_counter() - start) * 1000,
    )
    return purged


def scheduled_cleanup(open_store: "Callable[[], FolderStore]") -> Purged | None:
    """One scheduled pass; None when the flag is off, there is no file yet, or it will not open."""
    # Local: the store imports this module for `expiry_cutoff`.
    from app.folders.store import FoldersDisabledError, StoreConfigError

    try:
        folder_store = open_store()
        if not folder_store.path.exists():
            return None
        return cleanup(folder_store)
    except FoldersDisabledError:
        log.info("folder cleanup skipped: the folders flag is off")
    except StoreConfigError as exc:
        log.error("folder cleanup could not open the store: %s", exc)
    return None


async def run_cleanups(
    open_store: "Callable[[], FolderStore]",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> NoReturn:
    """Sleep a day, clean up off the event loop, repeat; ends only when cancelled."""
    while True:
        await sleep(CLEANUP_INTERVAL_SECONDS)
        await asyncio.to_thread(scheduled_cleanup, open_store)
