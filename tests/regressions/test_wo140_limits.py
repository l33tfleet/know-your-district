"""#182: atomic Ask admission, environment secrets and offline startup."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

from app.agent.answers import Answer, AnswerRenderer, Paused, Refuse
from app.copy import section_copy
from etl.boundaries import DistrictId


def test_missing_key_pauses_without_provider_and_app_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime import Runtime
    from app.main import app

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def forbidden(key: str) -> Answer:
        pytest.fail("provider called without key")

    result = Runtime().run("192.0.2.1", forbidden)
    assert isinstance(result, Paused)
    renderer = AnswerRenderer(DistrictId(chamber="house", district=22), [])
    assert renderer.render(result) == section_copy("ask")["paused"]
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200


def test_key_stays_out_of_logs_and_results(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.agent.runtime import Runtime

    secret = "test-only-sensitive-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    runtime = Runtime()

    def success(key: str) -> Answer:
        assert key == secret
        return Refuse(kind="refuse", reason="out_of_scope")

    def failure(key: str) -> Answer:
        raise RuntimeError(f"provider error containing {key}")

    results = [runtime.run("192.0.2.1", p) for p in (success, failure)]
    renderer = AnswerRenderer(DistrictId(chamber="house", district=22), [])
    assert results[0].kind == "refuse" and results[1].kind == "paused"
    assert secret not in caplog.text + repr(runtime) + repr(results)
    assert all(secret not in str(renderer.render(r)) for r in results)


def test_ip_minute_daily_exhaustion_and_utc_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.runtime import Runtime, Settings

    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-key")
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    runtime = Runtime(Settings(daily_input_tokens=1000000), clock=lambda: now)
    calls = 0

    def provider(key: str) -> Answer:
        nonlocal calls
        calls += 1
        return Refuse(kind="refuse", reason="out_of_scope")

    for minute in range(10):
        now = now.replace(minute=minute)
        assert all(runtime.run("192.0.2.1", provider).kind == "refuse" for _ in range(10))
        assert runtime.run("192.0.2.1", provider).kind == "paused"
    now += timedelta(minutes=1)
    assert runtime.run("192.0.2.1", provider).kind == "paused"
    assert calls == 100
    assert runtime.run("192.0.2.2", provider).kind == "refuse"
    now = now.replace(hour=0, minute=0) + timedelta(days=1)
    assert runtime.run("192.0.2.1", provider).kind == "refuse"


@pytest.mark.parametrize("same_ip", [False, True])
def test_concurrent_reservations_do_not_overspend(
    monkeypatch: pytest.MonkeyPatch, same_ip: bool
) -> None:
    from app.agent.runtime import Runtime, Settings

    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-key")
    runtime = Runtime(Settings(daily_input_tokens=30, request_input_tokens=10))
    release = Event()
    entered = Event()
    full = Event()
    lock = Lock()
    calls = 0

    def provider(key: str) -> Answer:
        nonlocal calls
        with lock:
            calls += 1
            if calls == 3:
                full.set()
        entered.set()
        assert release.wait(5)
        return Refuse(kind="refuse", reason="out_of_scope")

    with ThreadPoolExecutor(max_workers=20) as pool:
        first = pool.submit(runtime.run, "192.0.2.1", provider)
        assert entered.wait(5)
        # Reserve while a provider call remains in flight: no lock across calls.
        pending = [
            pool.submit(runtime.run, "192.0.2.1" if same_ip else f"192.0.2.{i + 2}", provider)
            for i in range(19)
        ]

        def forbidden(key: str) -> Answer:
            pytest.fail("exhausted budget invoked provider")

        try:
            assert full.wait(5)
            assert runtime.run("192.0.2.99", forbidden).kind == "paused"
        finally:
            release.set()
        results = [first.result(), *(f.result() for f in pending)]
    assert sum(r.kind == "refuse" for r in results) == 3
    assert sum(r.kind == "paused" for r in results) == 17


def test_failed_reservations_stay_charged_and_day_rollover_resets_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime import Runtime, Settings

    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-key")
    now = datetime(2026, 10, 30, 23, 59, tzinfo=UTC)
    runtime = Runtime(Settings(daily_input_tokens=10, request_input_tokens=10), clock=lambda: now)
    calls = 0

    def provider(key: str) -> Answer:
        nonlocal calls
        calls += 1
        raise TimeoutError("possibly billed")

    assert runtime.run("192.0.2.1", provider).kind == "paused"
    assert runtime.run("192.0.2.2", provider).kind == "paused"
    assert calls == 1
    now += timedelta(minutes=1)
    assert runtime.run("192.0.2.2", provider).kind == "paused"
    assert calls == 2


def test_tracked_provider_settings_and_no_legacy_provider() -> None:
    from pathlib import Path

    from app.agent.runtime import load_settings

    settings = load_settings()
    assert settings.base_url == "https://api.typesafe.ai/v1/systemone"
    assert settings.model == "jev-latest" and settings.timeout_seconds == 8
    assert settings.daily_input_tokens >= settings.request_input_tokens > 0
    for path in (
        "app/agent/runtime.py",
        "config.toml",
        "docs/agent.md",
        "docs/security-privacy.md",
    ):
        assert "deepseek" not in Path(path).read_text().lower()


def test_concurrent_ip_limit_and_rolling_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.runtime import Runtime, Settings

    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-key")
    now = datetime(2026, 10, 30, 12, 0, 30, tzinfo=UTC)
    runtime = Runtime(Settings(daily_input_tokens=1000000), clock=lambda: now)

    def provider(key: str) -> Answer:
        return Refuse(kind="refuse", reason="out_of_scope")

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(runtime.run, "192.0.2.1", provider) for _ in range(30)]
        results = [f.result() for f in futures]
    assert sum(r.kind == "refuse" for r in results) == 10

    def forbidden(key: str) -> Answer:
        pytest.fail("rate-limited request invoked provider")

    now += timedelta(seconds=30)  # crossing a wall-clock minute does not reset the window
    assert runtime.run("192.0.2.1", forbidden).kind == "paused"
    now += timedelta(seconds=29)
    assert runtime.run("192.0.2.1", forbidden).kind == "paused"
    now += timedelta(seconds=1)
    assert runtime.run("192.0.2.1", provider).kind == "refuse"
