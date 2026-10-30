"""Pure catalog identity and retirement rules; runtime never writes identity state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from etl.programs import Program

# Append-only identity ledger. Retired entries remain registered forever. The
# original official page anchors identity independently of changeable names.
# Register new catalog identities here; never reassign an existing ID.
PROGRAM_IDENTITIES = {
    "snap": "https://humanservices.hawaii.gov/bessd/snap/",
    "ga": "https://humanservices.hawaii.gov/bessd/ga/",
}


def validate_program_ids(programs: Sequence[Program]) -> None:
    """Reject duplicates, removed/renamed IDs and reuse of registered identities."""
    by_id: dict[str, Program] = {}
    for program in programs:
        if program.id in by_id:
            raise ValueError(f"Duplicate program ID: {program.id}")
        by_id[program.id] = program
    for program_id, official_url in PROGRAM_IDENTITIES.items():
        if program_id not in by_id:
            raise ValueError(
                f"Immutable program ID {program_id} missing; retain it with retired metadata"
            )
        if str(by_id[program_id].official_url) != official_url:
            raise ValueError(f"Program ID {program_id} cannot be reused for a different identity")


@dataclass(frozen=True)
class ProgramResolution:
    program: Program
    status: Literal["active", "no longer offered"]


def resolve_program_id(programs: Sequence[Program], program_id: str) -> ProgramResolution:
    """Resolve a validated catalog ID without discarding a retired record."""
    for program in programs:
        if program.id == program_id:
            return ProgramResolution(
                program, "no longer offered" if program.retired is not None else "active"
            )
    raise ValueError(f"Unknown program ID: {program_id}")
