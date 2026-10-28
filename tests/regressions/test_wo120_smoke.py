"""WO120: deployment smoke checks real HTTP pages and a cited district figure."""

import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from starlette.types import Receive, Scope, Send

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
HOUSE = "/brief/house/22"
STATIC = "/static/vendor/htmx-2.0.11.min.js"
PATHS = ["/healthz", "/", HOUSE, "/brief/senate/1", STATIC]


@pytest.fixture
def smoke_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic published-shaped population rows, never real observations."""
    path = tmp_path / "facts.db"
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        for geography in ("house:15:022:2022", "senate:15:001:2022", "state:15"):
            db.execute(
                """INSERT INTO facts
                (variable, geography, vintage, value, moe, cv, reliability,
                 source, table_id, method, endpoint, label)
                VALUES ('B01003_001E', ?, '2020–2024', 12345, 100, 0.005, 'reliable',
                        'Synthetic Census ACS fixture', 'B01003',
                        'published estimate and 90% margin of error',
                        'https://api.census.gov/data/2024/acs/acs5', 'Total population')""",
                (geography,),
            )
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    return path


@contextmanager
def live_app(overrides: dict[str, tuple[int, str]] | None = None) -> Generator[str]:
    """Serve the real app on an OS-assigned port; inject one broken response if requested."""

    async def served(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and overrides and scope["path"] in overrides:
            status, body = overrides[scope["path"]]
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": body.encode()})
        else:
            await app(scope, receive, send)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(served, log_level="critical", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "test server did not start"
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "test server did not stop"


def smoke(url: str, *, make: bool = False) -> subprocess.CompletedProcess[str]:
    command = (
        ["make", "smoke", f"BASE_URL={url}"]
        if make
        else [sys.executable, str(ROOT / "scripts/smoke.py"), url]
    )
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
    )


def test_make_smoke_passes_with_fixture_database(smoke_db: Path) -> None:
    with live_app() as url:
        result = smoke(url, make=True)
    assert result.returncode == 0, result.stdout + result.stderr
    for path in PATHS:
        assert f"GET {url}{path} -> 200" in result.stdout


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("status", [500, 201])
def test_smoke_rejects_failed_required_endpoint(smoke_db: Path, path: str, status: int) -> None:
    with live_app({path: (status, "broken")}) as url:
        result = smoke(url)
    assert result.returncode == 1
    assert f"GET {url}{path}: expected 200, got {status}" in result.stderr


def test_smoke_rejects_missing_database(
    smoke_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("KYD_FACTS_DB", str(missing))
    with live_app() as url:
        result = smoke(url)
    assert result.returncode == 1
    assert f"GET {url}{HOUSE}: missing cited House 22 figure" in result.stderr
    assert not missing.exists()


def population_html(
    *,
    value: str = "12345",
    table: str = "B01003",
    vintage: str = "2020–2024",
    geography: str = "house:15:022:2022",
) -> str:
    return f'''<div class="figure" data-figure="population">
    <p class="reading" data-geography="{geography}">
    <data class="value" value="{value}">{value}</data></p>
    <dl class="citation" data-geography="{geography}">
    <dd data-field="table_id">{table}</dd><dd data-field="vintage">{vintage}</dd>
    </dl></div>'''


@pytest.mark.parametrize(
    "body",
    [
        population_html(value=""),
        population_html(table=""),
        population_html(table="B19013"),
        population_html(vintage=""),
        population_html(vintage="2019–2023"),
        population_html(geography="state:15"),
        "<p>B01003 2020–2024</p>",
    ],
    ids=[
        "no-value",
        "no-table",
        "wrong-table",
        "no-vintage",
        "wrong-vintage",
        "state-only",
        "no-figure",
    ],
)
def test_smoke_rejects_200_without_cited_district_figure(smoke_db: Path, body: str) -> None:
    with live_app({HOUSE: (200, body)}) as url:
        result = smoke(url)
    assert result.returncode == 1
    assert f"GET {url}{HOUSE}: missing cited House 22 figure" in result.stderr


def test_smoke_accepts_zero_population(smoke_db: Path) -> None:
    with live_app({HOUSE: (200, population_html(value="0"))}) as url:
        result = smoke(url)
    assert result.returncode == 0, result.stdout + result.stderr
