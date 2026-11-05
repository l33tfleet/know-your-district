# ruff: noqa: N999 -- sections are named NN_name.py by convention
"""Optional program detail, independently discovered and kept off the printout."""

from pathlib import Path

from app.copy import geography_name, section_copy
from app.page_state import PageState
from app.tools.program_stats import resolve_statistics
from etl.programs import load_catalog
from etl.programs.contracts import load_organisations

PRINT = False
CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


def context(state: PageState) -> dict[str, object]:
    copy = section_copy("profiles")
    organisations = load_organisations()
    profiles: list[dict[str, object]] = []
    for program in load_catalog(CATALOG):
        if program.retired is not None or not any(
            (program.rules, program.next_steps, program.enrichment)
        ):
            continue
        statistics: list[dict[str, object]] = []
        for fact in resolve_statistics(program, state.district):
            statistics.append(
                {
                    "fact": fact,
                    "geography": geography_name(fact.geography) if fact else None,
                    "scope": copy["district"]
                    if fact and fact.geography == state.district.fact_key
                    else copy["context"],
                    "value": f"{fact.value:,.6f}".rstrip("0").rstrip(".")
                    if fact and fact.value is not None
                    else copy["unavailable"],
                    "moe": copy["moe"].format(value=f"{fact.moe:,.6f}".rstrip("0").rstrip("."))
                    if fact and fact.moe is not None
                    else copy["no_moe"],
                    "reliability": copy["reliability"][fact.reliability] if fact else None,
                }
            )
        profiles.append(
            {
                "program": program,
                "statistics": statistics,
                "organisation": organisations[program.next_steps.contact.organisation_id].name
                if program.next_steps
                else None,
            }
        )
    return {"profiles": profiles}
