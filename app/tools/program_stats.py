"""Resolve catalog references through FactStore; YAML observations are never evidence."""

from app.facts import FactStore
from app.models import Fact
from etl.boundaries import DistrictId
from etl.programs import Program


def resolve_statistics(program: Program, district: DistrictId) -> list[Fact | None]:
    """Detached exact-key facts, or explicit absence; another district is never local.

    County/state observations are context, labeled by the profile renderer. No
    reference means no evidence, even when offline YAML observations are present.
    """
    enrichment = program.enrichment
    if enrichment is None:
        return []
    refs = enrichment.fact_references
    if not refs:
        return [None] if enrichment.stats else []
    store = FactStore.default()
    facts: list[Fact | None] = []
    for ref in refs:
        if ref.geography.startswith(("house:", "senate:")) and ref.geography != district.fact_key:
            facts.append(None)
            continue
        key = (ref.variable, ref.geography)
        facts.append(store.get([key], ref.vintage).get(key))
    return facts
