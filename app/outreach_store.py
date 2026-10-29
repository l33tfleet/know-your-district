"""Outreach observations use the existing read-only FactStore and Fact contract."""

from pathlib import Path

from app.facts import FactStore


def outreach_store() -> FactStore:
    return FactStore(Path(__file__).resolve().parents[1] / "data/outreach/facts/facts.db")
