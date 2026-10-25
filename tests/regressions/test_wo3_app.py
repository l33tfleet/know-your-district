"""WO #3: the minimal app serves `/healthz` and a placeholder home page, and
`make smoke BASE_URL=…` checks `/healthz` against a running app."""

import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]


def test_healthz_returns_200() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200


def test_home_page_returns_html() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_vendored_htmx_is_2_0_x() -> None:
    vendored = sorted((ROOT / "static" / "vendor").glob("htmx-*.min.js"))
    assert [p.name.startswith("htmx-2.0.") for p in vendored] == [True]
    response = TestClient(app).get(f"/static/vendor/{vendored[0].name}")
    assert response.status_code == 200


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live_url() -> Iterator[str]:
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{url}/healthz", timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_make_smoke_passes_against_running_app(live_url: str) -> None:
    result = subprocess.run(
        ["make", "smoke", f"BASE_URL={live_url}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_smoke_fails_when_nothing_is_listening() -> None:
    url = f"http://127.0.0.1:{free_port()}"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke.py"), url],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
