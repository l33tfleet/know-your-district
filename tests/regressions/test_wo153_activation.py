"""#397, step 3 of #153: the folder guards run in the production app, and cleanup is scheduled.

Every test drives `app.main.app` itself, with its lifespan where startup matters: the private
headers and body cap wrap the real folder routes, startup installs log redaction, and startup
plus a repeating task remove what has been expired for 180 days, only while the flag allows writes.
"""

import io
import logging
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn.logging import AccessFormatter

from app import features
from app.folders import retention, routes, service, store
from app.main import app as asgi_app
from app.page_state import PageState, page_state

FOLDER = "a" * 32
ABSENT = "0" * 32
FORM = {"content-type": "application/x-www-form-urlencoded"}
# An empty folder for House 22; `&` alone parses to no fields, so a body can be padded freely.
EMPTY_FOLDER = "/folders?district=house-22"
PRIVATE = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex",
}
START = datetime(2026, 1, 1, tzinfo=UTC)
Flag = Callable[[str], None]


def private(headers: Mapping[str, str]) -> dict[str, str]:
    return {name: headers[name] for name in PRIVATE if name in headers}


def state() -> PageState:
    result = page_state("house", "22")
    assert result is not None
    return result


class Clock:
    def __init__(self) -> None:
        self.moment = START

    def __call__(self) -> str:
        return self.moment.isoformat(timespec="seconds")

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "folders.db"
    monkeypatch.setenv("KYD_FOLDERS_DB", str(path))
    # No test reaches the real home, even one that clears `KYD_FOLDERS_DB`.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return path


@pytest.fixture
def flag(tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flag:
    def write(status: str) -> None:
        policy = tmp_path / "features.toml"
        policy.write_text(f'outreach = "on"\nfolders = "{status}"\n', encoding="utf-8")
        monkeypatch.setattr(features, "FEATURES_PATH", policy)

    write("on")
    return write


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(store, "now", fake)
    return fake


@pytest.fixture
def client(flag: Flag) -> TestClient:
    return TestClient(asgi_app, follow_redirects=False)


def folder_count(path: Path) -> int:
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute("SELECT COUNT(*) FROM folders").fetchone()[0])


def make_folder(path: Path) -> str:
    folder_store = store.FolderStore(path, state())
    return folder_store.create_folder("Kalihi", "snap_no_receipt", "house", 22)


# --- private responses on the real folder routes ---


@pytest.mark.parametrize("target", [f"/f/{ABSENT}", f"/f/{ABSENT}/missing", "/folders"])
def test_folder_answers_are_private_even_when_refused(client: TestClient, target: str) -> None:
    assert private(client.get(target).headers) == PRIVATE


def test_a_saved_folder_redirect_is_private(client: TestClient, db_path: Path) -> None:
    response = client.post(EMPTY_FOLDER, content=b"", headers=FORM)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/f/")
    assert private(response.headers) == PRIVATE
    assert folder_count(db_path) == 1


def test_a_folder_page_is_private(client: TestClient, db_path: Path) -> None:
    folder_id = make_folder(db_path)
    response = client.get(f"/f/{folder_id}")
    assert response.status_code == 200
    assert private(response.headers) == PRIVATE


def test_folder_answers_are_private_with_the_flag_off(flag: Flag) -> None:
    flag("off")
    response = TestClient(asgi_app).get(f"/f/{ABSENT}")
    assert response.status_code == 404
    assert private(response.headers) == PRIVATE


def test_an_unhandled_folder_route_error_is_private(
    flag: Flag, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Starlette's ServerErrorMiddleware writes the 500; the guard must sit outside it."""

    def broken(_state: PageState) -> store.FolderStore:
        raise RuntimeError("injected folder-route failure")

    monkeypatch.setattr(routes, "open_store", broken)
    response = TestClient(asgi_app, raise_server_exceptions=False).get(f"/f/{ABSENT}")
    assert response.status_code == 500
    assert private(response.headers) == PRIVATE


def test_other_pages_are_not_marked_private(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert private(response.headers) == {}


# --- the body cap on the real folder routes ---


def test_a_body_past_the_cap_is_refused_before_any_write(client: TestClient, db_path: Path) -> None:
    body = b"&" * (service.MAX_BODY_BYTES + 1)
    response = client.post(EMPTY_FOLDER, content=body, headers=FORM)
    assert response.status_code == 413
    assert private(response.headers) == PRIVATE
    assert not db_path.exists()


def test_a_folder_route_body_past_the_cap_is_refused(client: TestClient, db_path: Path) -> None:
    folder_id = make_folder(db_path)
    body = b"status=done" + b"&" * service.MAX_BODY_BYTES
    response = client.post(f"/f/{folder_id}/cards/1/status", content=body, headers=FORM)
    assert response.status_code == 413


def test_a_body_at_the_cap_reaches_the_route(client: TestClient, db_path: Path) -> None:
    body = b"&" * service.MAX_BODY_BYTES
    response = client.post(EMPTY_FOLDER, content=body, headers=FORM)
    assert response.status_code == 303
    assert folder_count(db_path) == 1


# --- log redaction is installed at startup ---


@pytest.fixture
def no_redaction() -> Iterator[None]:
    def strip() -> None:
        for name in service.LOGGERS:
            logger = logging.getLogger(name)
            for filter_ in list(logger.filters):
                if isinstance(filter_, service.RedactFolderLinks):
                    logger.removeFilter(filter_)
            for handler in logger.handlers:
                for filter_ in list(handler.filters):
                    if isinstance(filter_, service.RedactFolderLinks):
                        handler.removeFilter(filter_)

    strip()
    yield
    strip()


@pytest.fixture
def access_output(no_redaction: None) -> Iterator[io.StringIO]:
    """A uvicorn-style access handler, added before startup the way uvicorn's config adds it."""
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(AccessFormatter(fmt="%(request_line)s %(status_code)s", use_colors=False))
    logger = logging.getLogger("uvicorn.access")
    logger.addHandler(handler)
    level = logger.level
    logger.setLevel(logging.INFO)
    yield output
    logger.setLevel(level)
    logger.removeHandler(handler)


def access_line(path: str) -> None:
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", path, "1.1", 200
    )


def test_startup_redacts_folder_links_in_access_logs(
    client: TestClient, access_output: io.StringIO
) -> None:
    with client:
        access_line(f"/f/{FOLDER}/cards/3/status")
    text = access_output.getvalue()
    assert FOLDER not in text
    assert "GET /f/[redacted]/cards/3/status HTTP/1.1 200" in text


def test_without_startup_access_logs_are_not_touched(
    client: TestClient, access_output: io.StringIO
) -> None:
    """The control: only the production startup installs the filter."""
    access_line(f"/f/{FOLDER}")
    assert FOLDER in access_output.getvalue()


def test_startup_redacts_folder_links_in_error_logs(
    client: TestClient, no_redaction: None, caplog: pytest.LogCaptureFixture
) -> None:
    with client:
        logging.getLogger("uvicorn.error").error("failed on https://example.org/f/%s", FOLDER)
    assert FOLDER not in caplog.text
    assert "/f/[redacted]" in caplog.text


def test_redaction_is_installed_once_per_startup(client: TestClient, no_redaction: None) -> None:
    with client:
        pass
    with client:
        pass
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(item, service.RedactFolderLinks) for item in filters) == 1


# --- expiry: startup and a schedule remove what has been expired for 180 days ---


def test_startup_removes_an_expired_folder(client: TestClient, db_path: Path, clock: Clock) -> None:
    make_folder(db_path)
    clock.advance(days=180, seconds=1)
    with client:
        assert folder_count(db_path) == 0


def test_startup_keeps_a_live_folder(client: TestClient, db_path: Path, clock: Clock) -> None:
    make_folder(db_path)
    clock.advance(days=179)
    with client:
        assert folder_count(db_path) == 1


def test_cleanup_repeats_while_the_app_runs(
    client: TestClient, db_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention, "CLEANUP_INTERVAL_SECONDS", 0.05)
    make_folder(db_path)
    with client:
        assert folder_count(db_path) == 1
        clock.advance(days=181)
        deadline = time.monotonic() + 5
        while folder_count(db_path) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert folder_count(db_path) == 0


def test_the_schedule_runs_daily() -> None:
    assert timedelta(seconds=retention.CLEANUP_INTERVAL_SECONDS) == timedelta(days=1)


def test_cleanup_runs_with_the_flag_in_preview(
    client: TestClient, flag: Flag, db_path: Path, clock: Clock
) -> None:
    """Preview requests write folders, so their folders expire too."""
    make_folder(db_path)
    flag("preview")
    clock.advance(days=181)
    with client:
        assert folder_count(db_path) == 0


# --- flag off: startup writes nothing ---


def test_flag_off_cleanup_leaves_the_store_alone(
    client: TestClient, flag: Flag, db_path: Path, clock: Clock
) -> None:
    make_folder(db_path)
    flag("off")
    clock.advance(days=181)
    with client:
        assert client.get("/healthz").status_code == 200
    assert folder_count(db_path) == 1


def test_flag_off_startup_creates_no_store(
    client: TestClient, flag: Flag, db_path: Path, tmp_path: Path
) -> None:
    flag("off")
    with client:
        pass
    assert not db_path.exists()
    assert not (tmp_path / "know-your-district").exists()


def test_flag_on_startup_creates_no_store_either(client: TestClient, db_path: Path) -> None:
    """Cleanup only removes rows: with no file yet there is nothing to remove or create."""
    with client:
        pass
    assert not db_path.exists()


def test_a_misplaced_store_is_logged_and_the_app_still_starts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("KYD_FOLDERS_DB", str(Path(__file__).with_name("inside.db")))
    with client:
        assert client.get("/healthz").status_code == 200
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("folder cleanup" in r.getMessage() for r in errors)
    assert not Path(__file__).with_name("inside.db").exists()


def test_a_store_sqlite_cannot_read_is_logged_and_the_app_still_starts(
    client: TestClient, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A damaged or locked file fails in SQLite, not in the store's config checks."""
    db_path.write_bytes(b"not a database" * 100)
    db_path.chmod(0o600)
    with client:
        assert client.get("/healthz").status_code == 200
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("folder cleanup" in r.getMessage() for r in errors)


def wait_for(condition: Callable[[], bool], seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


def test_a_failed_scheduled_pass_does_not_stop_the_schedule(
    client: TestClient,
    db_path: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The file stays damaged until a background pass has failed; a later pass then purges."""
    monkeypatch.setattr(retention, "CLEANUP_INTERVAL_SECONDS", 0.05)
    passes: list[tuple[retention.Purged | None, int]] = []
    original = retention.scheduled_cleanup

    def sqlite_failures() -> int:
        return sum(
            r.levelno == logging.ERROR and "folder cleanup failed in SQLite" in r.getMessage()
            for r in caplog.records
        )

    def recorded(open_store: Callable[[], store.FolderStore]) -> retention.Purged | None:
        result = original(open_store)
        passes.append((result, sqlite_failures()))
        return result

    monkeypatch.setattr(retention, "scheduled_cleanup", recorded)
    db_path.write_bytes(b"not a database" * 100)
    db_path.chmod(0o600)
    with client:
        # Startup's pass failed; now a scheduled pass, in the background, fails the same way.
        assert passes == [(None, 1)]
        assert wait_for(lambda: len(passes) >= 2)
        assert passes[1] == (None, 2)
        assert client.get("/healthz").status_code == 200
        failed = len(passes)
        db_path.unlink()
        make_folder(db_path)
        assert folder_count(db_path) == 1
        clock.advance(days=181)
        assert wait_for(lambda: any(r is not None and r.folders == 1 for r, _ in passes[failed:]))
        assert folder_count(db_path) == 0


# --- the privacy note states the store and its guards as built ---
# Replaces test_journey_folder_save.py::test_privacy_note_states_the_folder_store_facts, whose
# "no automatic purge or retention period" stopped being true when cleanup was scheduled.


def privacy_note() -> str:
    path = Path(__file__).resolve().parents[2] / "docs/security-privacy.md"
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize(
    "fact",
    [
        "KYD_FOLDERS_DB",
        "know-your-district/folders.db",
        "~/.local/state",
        "`app/folders/store.py`",
        "0600",
        "at most 200 characters",
        "128-bit link",
        "`deleted_at`",
        "../app/folders/store.py",
        "../app/folders/schema.sql",
        "purges folders unwritten for 180 days (startup, daily)",
        "no-store, no-referrer, noindex",
        "bodies over 16 KiB: 413",
        "Only app logs redact folder links",
        "../app/folders/retention.py",
    ],
)
def test_privacy_note_states_the_folder_store_and_guard_facts(fact: str) -> None:
    assert fact in privacy_note()


@pytest.mark.parametrize(
    "stale",
    ["no automatic purge", "retention period exists", "folder links grant access to log readers"],
)
def test_privacy_note_no_longer_denies_cleanup_or_redaction(stale: str) -> None:
    assert stale not in privacy_note()


def test_privacy_note_numbers_match_the_code() -> None:
    assert service.MAX_BODY_BYTES == 16 * 1024
    assert timedelta(days=180) == retention.RETENTION
    expected = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex",
    }
    assert expected == service.PRIVATE_HEADERS
