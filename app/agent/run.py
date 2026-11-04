"""Admit one Ask classification, then resolve only page-bound tool results."""

from collections.abc import Sequence

from markupsafe import Markup

from app.agent.answers import AnswerRenderer, Reference, Routed
from app.agent.provider import Provider, Transport, http_transport
from app.agent.runtime import Runtime
from app.counties import load_mapping
from app.models import Fact
from app.tools.facts import DistrictFacts
from etl.boundaries import DistrictId


def ask(
    question: str,
    district: DistrictId,
    ip: str,
    runtime: Runtime,
    *,
    transport: Transport = http_transport,
    case_ids: Sequence[str] = ("snap_no_receipt",),
) -> Markup:
    """#184 supplies trusted client IP and the page's visible case IDs.

    Share the Runtime across requests; the provider is per request. No SQLite
    connection crosses a provider call. Numbers and comparison wording come from
    the established fact tools and AnswerRenderer, never from the transport.
    """
    provider = Provider(runtime.settings, transport=transport, case_ids=case_ids)
    answer = runtime.run(ip, lambda key: provider.decide(question, district, key))
    facts: list[Fact] = []
    if isinstance(answer, Routed) and answer.indicator_id not in (None, "none"):
        tool = DistrictFacts(district)
        geographies = [district.fact_key]
        if provider.compare:
            geographies.extend(s.county for s in load_mapping()[district.fact_key])
            geographies.append("state:15")
        for geography in geographies:
            fact = tool.get_facts(geography, [answer.indicator_id])[answer.indicator_id]
            if fact is not None:
                facts.append(fact)
        answer = answer.model_copy(
            update={
                "references": tuple(
                    Reference(variable=f.variable, geography=f.geography, vintage=f.vintage)
                    for f in facts
                )
            }
        )
    return AnswerRenderer(district, facts).render(answer)
