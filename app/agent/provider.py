"""TypeSafe facade: one typed classification, no generated text or upstream shapes outside.

Wire contract: https://docs.typesafe.ai/api/system-one and /primitives/choice.
Transport injection supports recorded responses without network access or credentials.
"""

import json
import math
import time
import tomllib
from collections.abc import Callable, Sequence
from http.client import HTTPException
from pathlib import Path
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from typing import Annotated, Literal
from urllib.request import Request

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.answers import Alternative, Answer, Clarify, Paused, Refuse, Routed
from app.agent.runtime import Settings
from etl.boundaries import DistrictId

Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Transport = Callable[[str, str, bytes, float], bytes]
# No retries, at most four in-flight transports even if an injected transport hangs.
_SLOTS = BoundedSemaphore(4)
_RESPONSE_BYTES = 65536
INDIVIDUAL = (
    "The question is about one specific person (the asker or someone they know) "
    "rather than residents of the district as a group."
)
COMPARE = "The question asks how this district compares with another place, such as the county or the state."
TOPICS = {
    "population": "Total population: all residents; not an age subgroup or household count.",
    "age_65_share": "Kūpuna: share of residents age 65 and over; not a count or fixed-income measure.",
    "median_household_income": "Median household income; not individual income or program eligibility.",
    "snap_no_receipt": (
        "Food assistance, SNAP, hunger, households in poverty not receiving SNAP; "
        "an outreach signal, not eligibility or a measured enrollment gap."
    ),
    "none": "No listed measure covers the question, including crime or partisan opinions.",
}


class RoutingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    confidence_threshold: Probability = 0.6
    individual_threshold: Probability = 0.8
    compare_threshold: Probability = 0.6
    alternative_threshold: Probability = 0.15


def load_routing() -> RoutingSettings:
    with (Path(__file__).resolve().parents[2] / "config.toml").open("rb") as stream:
        return RoutingSettings.model_validate(tomllib.load(stream)["ask_routing"])


class _Choice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["choice"]
    choice: str
    confidence: Probability
    probabilities: dict[str, Probability]


class _Noul(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["noul"]
    noul: Probability


class _Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: _Choice
    individual: _Noul
    compare: _Noul


class _Usage(BaseModel):
    input_tokens: Annotated[int, Field(strict=True, ge=0)]
    output_tokens: Annotated[int, Field(strict=True, ge=0)]


class _Response(BaseModel):
    model: str
    answers: _Answers
    usage: _Usage


def http_transport(url: str, key: str, body: bytes, timeout: float) -> bytes:
    """POST once; redirects are rejected so a credential cannot leave the endpoint."""
    from urllib.request import HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args: object, **kwargs: object) -> None:
            return None

    request = Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    # An outer wall-clock bound also covers DNS and a trickling response.
    with build_opener(NoRedirect).open(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError("upstream status")
        return response.read(_RESPONSE_BYTES + 1)


class Provider:
    """Page-bound classification; measurements and evidence never go to Jev."""

    def __init__(
        self,
        settings: Settings,
        *,
        routing: RoutingSettings | None = None,
        transport: Transport = http_transport,
        case_ids: Sequence[str] = ("snap_no_receipt",),
        indicator_ids: Sequence[str] = ("population", "age_65_share", "median_household_income"),
    ) -> None:
        self.settings = settings
        self.routing = routing if routing is not None else load_routing()
        self.transport = transport
        if any(i != "snap_no_receipt" for i in case_ids):
            raise ValueError("valid cases: snap_no_receipt")
        if any(i not in tuple(TOPICS)[:3] for i in indicator_ids):
            raise ValueError("valid indicators: population, age_65_share, median_household_income")
        self.topics = {i: TOPICS[i] for i in (*case_ids, *indicator_ids, "none")}
        if len(self.topics) < 3:
            raise ValueError("page must offer at least two topics")
        self.last_latency_seconds: float | None = None
        self.compare = False

    def decide(self, question: str, district: DistrictId, key: str) -> Answer:
        """Return only local contracts. Invalid upstream output fails closed to paused."""
        self.compare = False
        if not question.strip() or any(ord(c) < 0x20 for c in question):
            raise ValueError("question must be nonblank text without control characters")
        payload = {
            "model": self.settings.model,
            "state": {
                "question": question,
                "chamber": district.chamber,
                "district": district.district,
                "topics": [
                    {"id": i, "label": label, "population": label}
                    for i, label in self.topics.items()
                    if i != "none"
                ],
            },
            "questions": {
                "topic": {
                    "type": "choice",
                    "instructions": "Which page topic covers the question?",
                    "criteria": self.topics,
                },
                "individual": {"type": "noul", "instructions": INDIVIDUAL},
                "compare": {"type": "noul", "instructions": COMPARE},
            },
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        # Conservative UTF-8 byte allowance for all three independent evaluations,
        # plus framing reserve. Do not estimate tokens from characters or words.
        if 3 * len(body) + 512 > self.settings.request_input_tokens:
            return Paused(kind="paused")
        if not _SLOTS.acquire(blocking=False):
            return Paused(kind="paused")
        result: Queue[bytes | Exception] = Queue(maxsize=1)

        def send() -> None:
            try:
                result.put(
                    self.transport(self.settings.base_url, key, body, self.settings.timeout_seconds)
                )
            except Exception as exc:
                result.put(exc)
            finally:
                _SLOTS.release()

        started = time.monotonic()
        Thread(target=send, daemon=True).start()
        try:
            raw = result.get(timeout=self.settings.timeout_seconds)
            if isinstance(raw, (OSError, HTTPException)):
                return Paused(kind="paused")
            if isinstance(raw, Exception):
                raise raw
            return self.decode(raw)
        except Empty:
            return Paused(kind="paused")
        finally:
            self.last_latency_seconds = time.monotonic() - started

    def decode(self, raw: bytes) -> Answer:
        """Validate and route live or recorded Jev bytes without transport or admission.

        Use the same page catalog and routing thresholds as live decisions. Replace
        the comparison decision on every decode, including malformed responses.
        """
        self.compare = False
        if len(raw) > _RESPONSE_BYTES:
            return Paused(kind="paused")
        try:
            response = _Response.model_validate_json(raw)
            topic = response.answers.topic
            probabilities = topic.probabilities
            if (
                set(probabilities) != set(self.topics)
                or topic.choice not in self.topics
                or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.01)
                or probabilities[topic.choice] != max(probabilities.values())
            ):
                return Paused(kind="paused")
        except ValidationError:
            return Paused(kind="paused")
        self.compare = response.answers.compare.noul >= self.routing.compare_threshold
        if response.answers.individual.noul >= self.routing.individual_threshold:
            return Refuse(kind="refuse", reason="individual")

        def option(i: str, probability: float) -> Alternative:
            return (
                Alternative(case_id=i, probability=probability)
                if i == "snap_no_receipt"
                else Alternative(indicator_id=i, probability=probability)
            )

        alternatives = tuple(
            option(i, p)
            for i, p in sorted(probabilities.items(), key=lambda item: -item[1])
            if p >= self.routing.alternative_threshold
        )
        if topic.choice == "none" or topic.confidence < self.routing.confidence_threshold:
            # A confident none has no likely alternatives. Offer the page catalog
            # as a general clarifier, retaining actual probabilities (including zero).
            if len(alternatives) < 2:
                if topic.choice != "none":
                    return Paused(kind="paused")
                alternatives = tuple(option(i, probabilities[i]) for i in self.topics)
            return Clarify(kind="clarify", alternatives=alternatives)
        selected = option(topic.choice, probabilities[topic.choice])
        return Routed(
            kind="routed",
            case_id=selected.case_id,
            indicator_id=selected.indicator_id,
            confidence=topic.confidence,
            alternatives=alternatives,
        )
