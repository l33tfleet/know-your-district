"""How long a folder lives, and the callable cleanup; nothing here schedules it (#228).

A folder expires 180 days after its last write. The store refuses an expired folder from that
moment, so a late cleanup never extends its life. Cleanup needs the `folders` flag on, like every
other write to the store.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.folders.store import FolderStore

RETENTION = timedelta(days=180)
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
