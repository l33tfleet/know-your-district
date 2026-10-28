"""Read-only facade over the SQLite fact table (`data/facts.db`, or `$KYD_FACTS_DB`).

Callers get validated `Fact` models keyed by (variable, geography); SQLite shapes stay here.
"""

import logging
import os
import sqlite3
import time
import tomllib
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from app.models import Fact

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "facts.db"
log = logging.getLogger(__name__)


def acs_config() -> tuple[str, int]:
    """The pinned ACS vintage and district plan year from `config.toml`."""
    acs = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))["acs"]
    return str(acs["vintage"]), int(acs["district_plan"])


def facts_db_path() -> Path:
    return Path(os.environ.get("KYD_FACTS_DB") or DEFAULT_DB)


class FactStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def default(cls) -> "FactStore":
        return cls(facts_db_path())

    def get(self, keys: Iterable[tuple[str, str]], vintage: str) -> dict[tuple[str, str], Fact]:
        """Facts for the (variable, geography) keys; a missing database or row is just absent."""
        wanted = set(keys)
        if not wanted or not self.path.is_file():
            return {}
        start = time.perf_counter()
        columns = list(Fact.model_fields)
        placeholders = ", ".join("(?, ?)" for _ in wanted)
        query = (
            f"SELECT {', '.join(columns)} FROM facts "
            f"WHERE vintage = ? AND (variable, geography) IN (VALUES {placeholders})"
        )
        params = [vintage, *(part for key in sorted(wanted) for part in key)]
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            rows = db.execute(query, params).fetchall()
        facts = [Fact(**dict(zip(columns, row, strict=True))) for row in rows]
        log.info(
            "fact table read: %d rows in %.1f ms", len(facts), (time.perf_counter() - start) * 1000
        )
        return {(fact.variable, fact.geography): fact for fact in facts}
