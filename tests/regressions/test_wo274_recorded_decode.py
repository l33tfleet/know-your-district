"""#389: recorded Jev decoding is independent of live transport admission."""

import json
from threading import BoundedSemaphore

import pytest

from app.agent.answers import Paused
from app.agent.provider import Provider, RoutingSettings
from app.agent.runtime import Settings
from tests.regressions.test_wo140_agent import DISTRICT, RECORDINGS, Recording


def forbidden_transport(url: str, key: str, body: bytes, timeout: float) -> bytes:
    pytest.fail("recorded decoding must not call transport")


@pytest.mark.parametrize("record", [r for r in RECORDINGS if r.http_status == 200])
def test_recorded_decode_with_transport_slots_exhausted(
    record: Recording, monkeypatch: pytest.MonkeyPatch
) -> None:
    slots = BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    monkeypatch.setattr("app.agent.provider._SLOTS", slots)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    # Neither a credential nor a live request's input allowance is needed.
    provider = Provider(Settings(request_input_tokens=1), transport=forbidden_transport)
    answer = provider.decode(json.dumps(record.response).encode())
    assert answer.kind == record.kind
    assert provider.compare == record.compare
    assert provider.last_latency_seconds is None
    assert not slots.acquire(blocking=False)


@pytest.mark.parametrize(
    "damage", ["json", "shape", "oversize", "catalog", "choice", "sum", "not_max", "prose"]
)
def test_recorded_decode_retains_malformed_response_handling(damage: str) -> None:
    # A valid comparison first ensures a rejected recording cannot retain its flag.
    provider = Provider(Settings(), transport=forbidden_transport)
    response = json.loads(json.dumps(RECORDINGS[5].response))
    assert provider.decode(json.dumps(response).encode()).kind == "routed"
    assert provider.compare
    topic = response["answers"]["topic"]
    if damage == "catalog":
        topic["probabilities"]["invented"] = 0
    elif damage == "choice":
        topic["choice"] = "invented"
    elif damage == "sum":
        topic["probabilities"]["population"] = 0.5
    elif damage == "not_max":
        topic["choice"] = "population"
    elif damage == "prose":
        topic["text"] = "untrusted generated prose"
    raw = json.dumps(response).encode()
    if damage == "json":
        raw = b"not JSON"
    elif damage == "shape":
        raw = b"{}"
    elif damage == "oversize":
        raw = b" " * 65537
    assert isinstance(provider.decode(raw), Paused)
    assert not provider.compare


def test_live_calls_share_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = json.dumps(RECORDINGS[0].response).encode()
    seen: list[bytes] = []

    def replay(url: str, key: str, body: bytes, timeout: float) -> bytes:
        return raw

    def decode(self: Provider, response: bytes) -> Paused:
        seen.append(response)
        return Paused(kind="paused")

    monkeypatch.setattr(Provider, "decode", decode)
    provider = Provider(Settings(), transport=replay)
    assert isinstance(provider.decide("hello", DISTRICT, "offline-placeholder"), Paused)
    assert seen == [raw]
    assert provider.last_latency_seconds is not None


def test_recorded_decode_uses_page_catalog_and_routing_thresholds() -> None:
    raw = json.dumps(RECORDINGS[4].response).encode()
    provider = Provider(Settings(), transport=forbidden_transport)
    assert provider.decode(raw).kind == "routed"
    strict = Provider(
        Settings(), routing=RoutingSettings(confidence_threshold=0.7), transport=forbidden_transport
    )
    assert strict.decode(raw).kind == "clarify"
    narrow = Provider(Settings(), case_ids=(), transport=forbidden_transport)
    assert isinstance(narrow.decode(raw), Paused)
