"""#183: replay Jev decisions without a network or a real credential.

Fixtures reconstruct wire envelopes from the operator-supplied scalar measurements.
Remaining probabilities and usage are deterministic test data, not live captures.
"""

import json
import time
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, TypeAdapter

from app.agent.answers import Clarify, Paused, Refuse, Routed
from app.agent.provider import Provider, RoutingSettings
from app.agent.run import ask
from app.agent.runtime import Runtime, Settings
from etl.boundaries import DistrictId

DISTRICT = DistrictId(chamber="house", district=22)


class Recording(BaseModel):
    question: str
    response: dict[str, object]
    kind: Literal["routed", "clarify", "refuse", "paused"]
    target: str | None = None
    compare: bool = False
    http_status: int = 200


RECORDINGS = TypeAdapter(list[Recording]).validate_json(
    (Path(__file__).parent / "fixtures/wo140_model.json").read_text()
)


@pytest.mark.parametrize("record", RECORDINGS, ids=[r.question for r in RECORDINGS])
def test_recorded_jev_routes(record: Recording, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    calls: list[bytes] = []

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        calls.append(body)
        assert url == Settings().base_url and key == "offline-placeholder"
        assert timeout == 8
        payload = json.loads(body)
        assert payload["state"]["question"] == record.question
        assert payload["state"]["chamber"] == "house"
        assert payload["state"]["district"] == 22
        assert set(payload["questions"]) == {"topic", "individual", "compare"}
        assert set(payload["questions"]["topic"]["criteria"]) == {
            "population",
            "age_65_share",
            "median_household_income",
            "snap_no_receipt",
            "none",
        }
        assert "values" not in payload["state"]
        if record.http_status != 200:
            from http.client import HTTPMessage
            from urllib.error import HTTPError

            raise HTTPError(url, record.http_status, "Unavailable", HTTPMessage(), None)
        return json.dumps(record.response).encode()

    provider = Provider(Settings(), transport=replay)
    answer = provider.decide(record.question, DISTRICT, "offline-placeholder")
    assert len(calls) == 1
    assert answer.kind == record.kind
    if isinstance(answer, Routed):
        assert (answer.case_id or answer.indicator_id) == record.target
        assert bool(answer.references) is False  # only local tools may attach evidence
    if isinstance(answer, Clarify) and record.question != "What's the crime rate?":
        assert {a.indicator_id for a in answer.alternatives} == {"median_household_income", "none"}
        assert all(a.probability >= 0.15 for a in answer.alternatives)
    if isinstance(answer, Refuse):
        assert answer.reason == "individual"


@pytest.mark.parametrize("record", RECORDINGS, ids=[r.question for r in RECORDINGS])
def test_orchestration_renders_tool_facts_and_shared_comparison(
    monkeypatch: pytest.MonkeyPatch,
    record: Recording,
) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-placeholder")

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        if record.http_status != 200:
            raise OSError("recorded upstream outage")
        return json.dumps(record.response).encode()

    html = str(ask(record.question, DISTRICT, "192.0.2.1", Runtime(), transport=replay))
    if record.target == "age_65_share":
        assert "65" in html and "%" in html and "never computed from the share" in html
    if record.compare:
        assert "compared with Honolulu County" in html
        assert "B19013" in html
        from app.analysis.outreach import compare_facts
        from app.copy import section_copy
        from app.tools.facts import DistrictFacts

        tool = DistrictFacts(DISTRICT)
        a = tool.get_facts(DISTRICT.fact_key, ["median_household_income"])[
            "median_household_income"
        ]
        b = tool.get_facts("county:15:003", ["median_household_income"])["median_household_income"]
        word = section_copy("ask")["comparisons"][compare_facts(a, b)]
        assert f"compared with Honolulu County: {word}" in html
    if record.target == "population":
        assert "B01003_001E" in html and "±" in html and "reliable" in html
    if record.target == "snap_no_receipt":
        assert "DHS decides eligibility" in html
    if record.kind == "paused":
        assert "paused" in html
    assert "offline-placeholder" not in html


@pytest.mark.parametrize("failure", ["timeout", "transport", "bad_json", "bad_shape", "slow"])
def test_failures_pause_without_leaking(
    failure: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "sensitive-credential")
    calls: list[int] = []

    def broken(url: str, key: str, body: bytes, timeout: float) -> bytes:
        calls.append(1)
        if failure == "timeout":
            raise TimeoutError(key)
        if failure == "transport":
            raise OSError(key)
        if failure == "slow":
            time.sleep(0.1)
        return b"not JSON" if failure == "bad_json" else b"{}"

    runtime = Runtime(Settings(timeout_seconds=0.02))
    started = time.monotonic()
    answer = Provider(runtime.settings, transport=broken).decide("hello", DISTRICT, "fake")
    assert time.monotonic() - started < 0.09
    assert isinstance(answer, Paused)
    html = str(answer)
    assert "paused" in html.lower()
    assert len(calls) == 1
    assert "sensitive-credential" not in html + caplog.text


def test_missing_key_and_oversize_input_never_call_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(url: str, key: str, body: bytes, timeout: float) -> bytes:
        pytest.fail("unexpected transport")

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert "paused" in str(ask("hello", DISTRICT, "192.0.2.1", Runtime(), transport=forbidden))
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-placeholder")
    assert "paused" in str(ask("界" * 9000, DISTRICT, "192.0.2.1", Runtime(), transport=forbidden))


def test_configurable_threshold_and_page_topics() -> None:
    record = RECORDINGS[4]

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return json.dumps(record.response).encode()

    answer = Provider(
        Settings(), routing=RoutingSettings(confidence_threshold=0.7), transport=replay
    ).decide(record.question, DISTRICT, "offline-placeholder")
    # A narrow page must not accept a topic that was not offered.
    assert isinstance(answer, Clarify)
    unavailable = Provider(Settings(), transport=replay, case_ids=())
    assert isinstance(unavailable.decide(record.question, DISTRICT, "offline-placeholder"), Paused)


@pytest.mark.parametrize("value", [float("nan"), -0.01, 1.01, "0.9", True])
def test_invalid_probabilities_pause(value: object) -> None:
    record = json.loads(json.dumps(RECORDINGS[0].response))
    record["answers"]["individual"]["noul"] = value

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return json.dumps(record).encode()

    assert isinstance(
        Provider(Settings(), transport=replay).decide("hello", DISTRICT, "fake"), Paused
    )


@pytest.mark.parametrize("status", [200, 400, 401, 429, 500, 503])
def test_http_transport_auth_status_and_no_redirects(
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from http.client import HTTPMessage
    from io import BytesIO
    from typing import Self
    from urllib.request import HTTPRedirectHandler, Request

    from app.agent.provider import http_transport

    calls: list[Request] = []

    class Reply:
        def __init__(self) -> None:
            self.status = status

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self, size: int) -> bytes:
            assert size == 65537
            return json.dumps(RECORDINGS[0].response).encode()

    class Opener:
        def open(self, request: Request, *, timeout: float) -> Reply:
            calls.append(request)
            assert request.get_method() == "POST"
            assert request.get_header("Authorization") == "Bearer offline-placeholder"
            assert request.get_header("Content-type") == "application/json"
            assert timeout == Settings().timeout_seconds
            return Reply()

    def opener(handler: type[HTTPRedirectHandler]) -> Opener:
        assert (
            handler().redirect_request(
                Request("https://configured.test"),
                BytesIO(),
                302,
                "redirect",
                HTTPMessage(),
                "https://other.test",
            )
            is None
        )
        return Opener()

    monkeypatch.setattr("urllib.request.build_opener", opener)
    answer = Provider(Settings(), transport=http_transport).decide(
        "hello", DISTRICT, "offline-placeholder"
    )
    assert len(calls) == 1
    assert isinstance(answer, Routed if status == 200 else Paused)


@pytest.mark.parametrize("individual,compare", [(0.799, 0.599), (0.8, 0.6), (0.801, 0.601)])
def test_atomic_noul_thresholds(individual: float, compare: float) -> None:
    response = json.loads(json.dumps(RECORDINGS[5].response))
    response["answers"]["individual"]["noul"] = individual
    response["answers"]["compare"]["noul"] = compare

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return json.dumps(response).encode()

    provider = Provider(Settings(), transport=replay)
    answer = provider.decide("hello", DISTRICT, "offline-placeholder")
    assert isinstance(answer, Refuse if individual >= 0.8 else Routed)
    assert provider.compare == (compare >= 0.6)


@pytest.mark.parametrize("damage", ["unknown", "missing", "sum", "not_max", "text", "oversize"])
def test_invalid_response_contracts_pause(damage: str) -> None:
    response = json.loads(json.dumps(RECORDINGS[0].response))
    topic = response["answers"]["topic"]
    if damage == "unknown":
        topic["choice"] = "invented"
    elif damage == "missing":
        del response["answers"]["compare"]
    elif damage == "sum":
        topic["probabilities"]["population"] = 0.5
    elif damage == "not_max":
        topic["choice"] = "population"
    elif damage == "text":
        topic["text"] = "There are 999 eligible people"

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return b" " * 65537 if damage == "oversize" else json.dumps(response).encode()

    assert isinstance(
        Provider(Settings(), transport=replay).decide("hello", DISTRICT, "fake"), Paused
    )


@pytest.mark.parametrize("question", ["", "   ", "hello\x00", "hello\nworld"])
def test_invalid_question_does_not_reach_upstream(question: str) -> None:
    def forbidden(url: str, key: str, body: bytes, timeout: float) -> bytes:
        pytest.fail("invalid question reached upstream")

    with pytest.raises(
        ValueError, match="question must be nonblank text without control characters"
    ):
        Provider(Settings(), transport=forbidden).decide(question, DISTRICT, "fake")


@pytest.mark.parametrize(
    "cases,indicators,error",
    [
        (("invented",), ("population",), "valid cases"),
        ((), ("invented",), "valid indicators"),
        ((), ("population",), "at least two topics"),
    ],
)
def test_invalid_page_catalog_fails_loudly(
    cases: tuple[str, ...],
    indicators: tuple[str, ...],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        Provider(Settings(), case_ids=cases, indicator_ids=indicators)


def test_local_transport_bug_is_not_published_as_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "sensitive-credential")

    def broken(url: str, key: str, body: bytes, timeout: float) -> bytes:
        raise TypeError(key)

    with pytest.raises(RuntimeError, match=r"^TypeError$"):
        ask("hello", DISTRICT, "192.0.2.1", Runtime(), transport=broken)


def test_transport_concurrency_stays_bounded_after_timeout() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    ready, release = Event(), Event()
    lock = Lock()
    calls = 0

    def blocked(url: str, key: str, body: bytes, timeout: float) -> bytes:
        nonlocal calls
        with lock:
            calls += 1
            if calls == 4:
                ready.set()
        assert release.wait(2)
        return json.dumps(RECORDINGS[0].response).encode()

    def decide() -> object:
        return Provider(Settings(timeout_seconds=0.05), transport=blocked).decide(
            "hello", DISTRICT, "fake"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(decide) for _ in range(4)]
        try:
            assert ready.wait(1)
            assert all(isinstance(p.result(), Paused) for p in pending)
            assert isinstance(decide(), Paused)
            assert calls == 4
        finally:
            release.set()


@pytest.mark.parametrize("confidence,kind", [(0.599, "clarify"), (0.6, "routed")])
def test_confidence_threshold_is_inclusive(confidence: float, kind: str) -> None:
    response = json.loads(json.dumps(RECORDINGS[4].response))
    response["answers"]["topic"]["confidence"] = confidence
    response["answers"]["topic"]["probabilities"] = {
        "age_65_share": 0.75,
        "median_household_income": 0.15,
        "none": 0.1,
        "population": 0,
        "snap_no_receipt": 0,
    }

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return json.dumps(response).encode()

    answer = Provider(Settings(), transport=replay).decide("hello", DISTRICT, "fake")
    assert answer.kind == kind
    if isinstance(answer, Clarify):
        assert {a.indicator_id for a in answer.alternatives} == {
            "age_65_share",
            "median_household_income",
        }


def test_ambiguous_answer_never_offers_options_below_probability_threshold() -> None:
    response = json.loads(json.dumps(RECORDINGS[4].response))
    response["answers"]["topic"]["confidence"] = 0.4
    response["answers"]["topic"]["probabilities"] = {
        "age_65_share": 0.8,
        "median_household_income": 0.1,
        "none": 0.1,
        "population": 0,
        "snap_no_receipt": 0,
    }

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return json.dumps(response).encode()

    # The reused Clarify contract needs two likely options. If there is only
    # one, use the canned fallback rather than inventing likely alternatives.
    assert isinstance(
        Provider(Settings(), transport=replay).decide("hello", DISTRICT, "fake"), Paused
    )
