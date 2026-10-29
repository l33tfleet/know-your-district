"""SNAP household outreach rows for future views; no eligibility estimates or ranking.

The state reference is its published household count and MOE divided by the
fixed number of districts in the selected chamber, never the statewide total.
This compares counts per district, not prevalence or program eligibility.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.analysis.reliability import Z90
from app.copy import section_copy
from app.facts import acs_config
from app.models import Fact
from app.outreach_store import outreach_store
from etl.boundaries import Chamber
from etl.programs import Program, load_catalog

VARIABLE = "B22003_006E"
STATE = "state:15"
DISTRICTS: dict[Chamber, int] = {"house": 51, "senate": 25}
Group = Literal["higher", "indeterminate", "lower", "caution", "missing"]


class OutreachRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    geography: str
    fact: Fact | None
    group: Group
    comparison: str
    reliability_word: str


class OutreachRows(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: tuple[OutreachRow, ...]
    state_basis: Fact | None
    basis_label: str
    measure: str
    caveat: str
    programs: tuple[Program, ...]


def _group(district: Fact | None, state: Fact | None) -> Group:
    if (
        district is None
        or state is None
        or district.value is None
        or state.value is None
        or district.vintage != state.vintage
    ):
        return "missing"
    if district.reliability == "caution" or state.reliability == "caution":
        return "caution"
    assert district.moe is not None and state.moe is not None
    # #30's reviewed rule: |a-b| / sqrt(MOEa² + MOEb²) > 1.645.
    # Squared Decimal arithmetic preserves the strict boundary and zero-MOE case.
    difference = Decimal(str(district.value)) - Decimal(str(state.value))
    variance = Decimal(str(district.moe)) ** 2 + Decimal(str(state.moe)) ** 2
    if difference**2 <= Z90**2 * variance:
        return "indeterminate"
    return "higher" if difference > 0 else "lower"


def build_rows(
    chamber: Chamber,
    facts: Mapping[tuple[str, str], Fact],
    programs: Sequence[Program],
) -> OutreachRows:
    """Build complete district-number-ordered rows from validated household facts.

    All original figures remain intact, including caution/unavailable figures.
    Only the explicitly derived state reference scales a published observation.
    """
    count = DISTRICTS[chamber]
    state = facts.get((VARIABLE, STATE))
    basis = None
    if state is not None:
        data = state.model_dump()
        data.update(
            value=state.value / count if state.value is not None else None,
            moe=state.moe / count if state.moe is not None else None,
            method=(
                f"derived state average per {chamber.capitalize()} district: published "
                f"B22003_006E estimate and 90% MOE each divided by {count} districts "
                f"in the 2022 plan; CV unchanged. Original method: {state.method}"
            ),
        )
        basis = Fact.model_validate(data)
    copy = section_copy("outreach")
    words = section_copy("figures")["reliability"]
    rows: list[OutreachRow] = []
    for number in range(1, count + 1):
        geography = f"{chamber}:15:{number:03}:2022"
        fact = facts.get((VARIABLE, geography))
        group = _group(fact, basis)
        rows.append(
            OutreachRow(
                geography=geography,
                fact=fact,
                group=group,
                comparison=copy["groups"][group],
                reliability_word=words[fact.reliability if fact is not None else "unavailable"],
            )
        )
    return OutreachRows(
        rows=tuple(rows),
        state_basis=basis,
        basis_label=copy["basis"].format(chamber=chamber.capitalize()),
        measure=copy["measure"],
        caveat=copy["caveat"],
        programs=tuple(p for p in programs if str(p.official_url) == copy["program_url"]),
    )


def load_rows(chamber: Chamber) -> OutreachRows:
    """Read published outreach facts and catalog referrals; close SQLite before returning."""
    vintage, _ = acs_config()
    geographies = [STATE, *(f"{chamber}:15:{n:03}:2022" for n in range(1, DISTRICTS[chamber] + 1))]
    facts = outreach_store().get(((VARIABLE, g) for g in geographies), vintage)
    catalog = load_catalog(Path(__file__).resolve().parents[2] / "data/programs.yaml")
    return build_rows(chamber, facts, catalog)
