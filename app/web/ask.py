"""Ask's HTTP edge: feature guard, bounded form input and page-bound typed decisions.

The provider facade alone owns upstream HTTP. One shared Runtime admits calls;
fact tools read detached rows after classification, with no open transaction.
"""

import json
import os
from datetime import date
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, JsonValue
from starlette.concurrency import run_in_threadpool

from app.agent.answers import VARIABLES, AnswerRenderer, Clarify, Paused, Routed
from app.agent.provider import TOPICS, Provider, http_transport
from app.agent.runtime import Runtime
from app.analysis.outreach import compare_facts
from app.brief_facts import FORMATS, citation, reading
from app.copy import geography_name, section_copy
from app.counties import load_mapping
from app.features import register_feature, require_feature
from app.page_state import PageState, page_state
from app.tools.facts import DistrictFacts

FEATURE = "ask"
register_feature(FEATURE)
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")
runtime = Runtime()
STORY_PATH = Path(__file__).resolve().parents[2] / "data/ask/story.json"
RECORDING_COPY_PATH = Path(__file__).resolve().parents[2] / "data/ask/copy.json"


class _Recording(BaseModel):
    """Only routing is recorded; the renderer always reads current fact rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    question: Literal["Where could food-assistance outreach help here?"]
    chamber: Literal["house"]
    district: Literal[22]
    recorded_on: date
    response: dict[str, JsonValue]


def _recording(state: PageState, question: str) -> _Recording | None:
    record = _Recording.model_validate_json(STORY_PATH.read_bytes())
    if (
        question == record.question
        and state.district.chamber == record.chamber
        and state.district.district == record.district
    ):
        return record
    return None


def answer_context(state: PageState, fields: dict[str, str], address: str) -> dict[str, object]:
    """Resolve only known page topics; upstream output never supplies text or figures."""
    provider = Provider(runtime.settings, transport=http_transport)
    recorded_on = None
    choice = fields.get("choice")
    if choice is not None:
        answer = Routed(
            kind="routed",
            case_id=choice if choice == "snap_no_receipt" else None,
            indicator_id=None if choice == "snap_no_receipt" else choice,
            confidence=1,
        )
    elif not os.environ.get("TYPESAFE_API_KEY", "").strip() and (
        record := _recording(state, fields["question"])
    ):
        raw = json.dumps(record.response).encode()

        def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
            return raw

        # Reuse the facade's validation and routing; this transport cannot make HTTP.
        provider = Provider(runtime.settings, transport=replay)
        answer = provider.decide(fields["question"], state.district, "recorded")
        if isinstance(answer, Routed) and answer.case_id == "snap_no_receipt":
            recorded_on = record.recorded_on.isoformat()
    else:
        answer = runtime.run(
            address, lambda key: provider.decide(fields["question"], state.district, key)
        )
    copy = section_copy("ask")
    context: dict[str, object] = {"copy": copy, "comparisons": [], "recorded_on": recorded_on}
    if recorded_on is not None:
        context["recording_label"] = json.loads(RECORDING_COPY_PATH.read_text())["recording_label"]
    if isinstance(answer, Clarify):
        context["clarify"] = copy["fixed_income" if answer.reason == "fixed_income" else "clarify"]
        context["options"] = [
            {
                "id": option.case_id or option.indicator_id,
                "label": section_copy("snap")["heading"]
                if option.case_id
                else copy["refusals"]["out_of_scope"]
                if option.indicator_id == "none"
                else copy["options"][option.indicator_id],
            }
            for option in sorted(answer.alternatives, key=lambda a: -a.probability)[:3]
        ]
    elif isinstance(answer, Routed) and answer.indicator_id in FORMATS:
        indicator = answer.indicator_id
        tool = DistrictFacts(state.district)
        geographies = [
            state.district.fact_key,
            *(s.county for s in load_mapping()[state.district.fact_key]),
            "state:15",
        ]
        facts = [tool.get_facts(g, [indicator])[indicator] for g in geographies]
        figures = section_copy("figures")
        fmt = FORMATS[indicator]
        # Render the existing figures template, including its exact citation and MOE
        # wording. This snapshot comes only from DistrictFacts tool results.
        context["figure_section"] = {
            "figures": [
                {
                    "key": indicator,
                    "variable": VARIABLES[indicator],
                    "name": figures["names"][indicator],
                    "district": reading(geographies[0], facts[0], fmt, figures),
                    "state": reading(geographies[-1], facts[-1], fmt, figures),
                    "counties": [
                        reading(g, fact, fmt, figures) | {"label": geography_name(g)}
                        for g, fact in zip(geographies[1:-1], facts[1:-1], strict=True)
                    ],
                    "citations": [
                        citation(fact, fmt, figures) for fact in facts if fact is not None
                    ],
                }
            ],
        }
        context["figures_copy"] = figures
        if indicator == "age_65_share":
            context["note"] = figures["count_unavailable"]
        if provider.compare and indicator != "population":
            context["comparisons"] = [
                copy["comparison"].format(
                    label=copy["options"][indicator],
                    district=geography_name(geographies[0]),
                    reference=geography_name(g),
                    conclusion=copy["comparisons"][compare_facts(facts[0], fact)],
                )
                for g, fact in zip(geographies[1:], facts[1:], strict=True)
            ]
    else:
        context["answer"] = AnswerRenderer(state.district, []).render(answer)
    return context


@router.post("/brief/{chamber}/{n}/ask", response_class=HTMLResponse)
async def ask_answer(
    request: Request,
    chamber: str,
    n: str,
    v: str | None = None,
    preview: str | None = None,
) -> HTMLResponse:
    """Disabled routes return 404 before reading input or admitting provider work."""
    if preview not in (None, "0", "1"):
        raise HTTPException(status_code=404)
    state = page_state(chamber, n, v, preview=preview == "1")
    if state is None:
        raise HTTPException(status_code=404)
    require_feature(FEATURE, state)
    if (
        request.headers.get("content-type", "").split(";", 1)[0]
        != "application/x-www-form-urlencoded"
    ):
        raise HTTPException(status_code=422, detail="Use an Ask form")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(status_code=413, detail="Ask form is too large")
    try:
        parsed = parse_qs(
            body.decode("utf-8"), keep_blank_values=True, errors="strict", max_num_fields=2
        )
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Ask form") from exc
    if set(parsed) not in ({"question"}, {"choice"}) or any(len(v) != 1 for v in parsed.values()):
        raise HTTPException(status_code=422, detail="Supply one question or one choice")
    fields = {key: values[0].strip() for key, values in parsed.items()}
    if "choice" in fields and fields["choice"] not in TOPICS:
        raise HTTPException(status_code=422, detail=f"Valid choices: {', '.join(TOPICS)}")
    if "question" in fields and (
        not fields["question"]
        or len(fields["question"]) > 2000
        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in parsed["question"][0])
    ):
        raise HTTPException(status_code=422, detail="Use nonblank text without control characters")
    # ASGI's peer address is trusted; raw forwarded headers never set rate-limit identity.
    address = request.client.host if request.client else ""
    try:
        ip_address(address)
    except ValueError:
        context: dict[str, object] = {
            "answer": AnswerRenderer(state.district, []).render(Paused(kind="paused"))
        }
    else:
        context = await run_in_threadpool(answer_context, state, fields, address)
    context["action"] = str(request.url)
    return templates.TemplateResponse(request, "partials/ask-answer.html", context)
