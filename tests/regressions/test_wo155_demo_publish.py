"""#413 (step 2 of #155): publish the demo folder and refresh it nightly.

The home page links "See an example outreach folder" only once the seed exists, so the link
never leads to a 404. The committed systemd units run `--matches --commit` with the app's own
environment file every night; a run replaces only the seed, never a visitor's private copy.
"""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.copy import load_copy
from app.folders import store
from tests.regressions.test_journey_folder_save import Flag, client, flag, folder_store, rows
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo155_match_seed import snapshot

__all__ = ["base_url", "browser", "client", "config", "flag", "page", "shipped_facts"]
ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "deploy/systemd"
SERVICE = UNITS / "kyd-demo-reset.service"
TIMER = UNITS / "kyd-demo-reset.timer"
SEED = f"/f/{store.DEMO_ID}"
LABEL = "See an example outreach folder"
Unit = dict[str, dict[str, list[str]]]


def unit(path: Path) -> Unit:
    """A systemd unit as section -> key -> values (a key may repeat)."""
    sections: Unit = {}
    current: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        key, _, value = line.partition("=")
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


def one(section: dict[str, list[str]], key: str) -> str:
    (value,) = section[key]
    return value


def service_command() -> list[str]:
    """ExecStart as the test runs it: this interpreter in place of the install's venv python."""
    service = unit(SERVICE)["Service"]
    argv = shlex.split(one(service, "ExecStart"))
    assert argv[0] == f"{one(service, 'WorkingDirectory')}/.venv/bin/python"
    return [sys.executable, *argv[1:]]


def run_service() -> subprocess.CompletedProcess[str]:
    return subprocess.run(service_command(), cwd=ROOT, capture_output=True, text=True, check=True)


def demo_link(html: str) -> str | None:
    links = [a for a in parse(html).find_all("a") if a.text == LABEL]
    assert len(links) <= 1
    return links[0].attrs["href"] if links else None


def test_service_runs_the_match_seed_with_the_apps_environment() -> None:
    sections = unit(SERVICE)
    service = sections["Service"]
    assert one(service, "Type") == "oneshot"
    assert shlex.split(one(service, "ExecStart"))[1:] == [
        "-m",
        "app.folders.demo",
        "--matches",
        "--commit",
    ]
    # The app's own environment file carries KYD_FOLDERS_DB, so both open the same store.
    environment = one(service, "EnvironmentFile")
    assert environment.startswith("/etc/")
    guide = (ROOT / "docs/demo-folder.md").read_text(encoding="utf-8")
    assert f"EnvironmentFile={environment}" in guide
    assert "KYD_FOLDERS_DB=" in guide
    assert one(service, "UMask") == "0077"  # a store the run creates is never group-readable
    assert "Install" not in sections  # only the timer starts it


def test_timer_fires_nightly_catches_up_and_starts_the_service() -> None:
    sections = unit(TIMER)
    timer = sections["Timer"]
    calendar = one(timer, "OnCalendar")
    assert calendar.startswith("*-*-* 0") and calendar.endswith(" Pacific/Honolulu")
    assert one(timer, "Persistent") == "true"  # a night missed while down runs at boot
    assert one(timer, "Unit") == SERVICE.name
    assert one(sections["Install"], "WantedBy") == "timers.target"
    analyze = shutil.which("systemd-analyze")
    if analyze is not None:  # where systemd is installed, it must parse the schedule too
        result = subprocess.run([analyze, "calendar", calendar], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "Next elapse" in result.stdout


def test_install_guide_seeds_before_the_link_appears() -> None:
    guide = " ".join((ROOT / "docs/demo-folder.md").read_text(encoding="utf-8").split())
    for step in (
        "deploy/systemd/kyd-demo-reset.service",
        "deploy/systemd/kyd-demo-reset.timer",
        "systemctl daemon-reload",
        "systemctl start kyd-demo-reset.service",
        "systemctl enable --now kyd-demo-reset.timer",
        "systemctl list-timers kyd-demo-reset.timer",
    ):
        assert step in guide
    assert guide.index("systemctl start kyd-demo-reset.service") < guide.index(
        "systemctl enable --now kyd-demo-reset.timer"
    )


def test_home_links_the_demo_only_once_the_seed_exists(client: TestClient, tmp_path: Path) -> None:
    assert load_copy()["home"]["demo_link"] == LABEL
    assert demo_link(client.get("/").text) is None
    assert not (tmp_path / "folders.db").exists()  # the home page never creates the store
    run_service()
    href = demo_link(client.get("/").text)
    assert href is not None and href == SEED
    response = client.get(href)
    assert response.status_code == 200
    document = parse(response.text)
    assert len(document.find_all("div", class_="folder-card")) == 3
    assert len(document.find_all("article", class_="case")) == 3
    assert response.text.count("Aloha United Way 211") >= 3


def test_home_hides_the_link_while_folders_are_off(flag: Flag, client: TestClient) -> None:
    run_service()
    off = flag("off")
    assert demo_link(off.get("/").text) is None
    assert off.get(SEED).status_code == 404


def test_nightly_run_restores_the_seed_and_keeps_visitor_copies(
    client: TestClient, tmp_path: Path
) -> None:
    run_service()
    db = folder_store(tmp_path / "folders.db")
    seed = snapshot(db, store.DEMO_ID)
    card = db.get_folder(store.DEMO_ID).cards[0].id
    response = client.post(f"{SEED}/cards/{card}/status", data={"status": "done"})
    assert response.status_code == 303
    copy = response.headers["location"].removeprefix("/f/").partition("#")[0]
    assert copy != store.DEMO_ID
    kept = snapshot(db, copy)
    kept_rows = rows(db.path, f"SELECT * FROM folders WHERE id = '{copy}'")
    assert snapshot(db, store.DEMO_ID) == seed  # the edit went to the copy
    for _ in range(2):
        run_service()
        assert snapshot(db, store.DEMO_ID) == seed
        assert snapshot(db, copy) == kept
        assert rows(db.path, f"SELECT * FROM folders WHERE id = '{copy}'") == kept_rows
    assert client.get(f"/f/{copy}").status_code == 200


@pytest.mark.parametrize(
    "fact",
    [
        "immutable",
        "private copy",
        "nightly",
        "phone numbers, emails and addresses",
        "../app/folders/demo.py",
        "../deploy/systemd/kyd-demo-reset.timer",
        "../etl/census.py",
    ],
)
def test_privacy_note_states_the_demo_seed_and_copies(fact: str) -> None:
    note = " ".join((ROOT / "docs/security-privacy.md").read_text(encoding="utf-8").split())
    assert fact in note


def test_privacy_note_no_longer_denies_persisted_user_content() -> None:
    note = " ".join((ROOT / "docs/security-privacy.md").read_text(encoding="utf-8").split())
    assert "or user content persist" not in note
    assert len(note.split()) <= 300


def test_browser_follows_the_home_link_to_the_complete_seed(
    page: Page,
    config: Path,
    shipped_facts: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config.write_text('outreach = "on"\nfolders = "on"\n', encoding="utf-8")
    monkeypatch.setenv("KYD_FOLDERS_DB", str(tmp_path / "folders.db"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    run_service()
    open_page(page, f"{shipped_facts}/", 1440)
    page.get_by_role("link", name=LABEL).click()
    page.wait_for_url(f"**{SEED}")
    assert page.locator(".folder-card").count() == 3
    assert page.locator("article.case").count() == 3
    assert page.locator(".case-source").count() == 3
    assert page.get_by_text("Aloha United Way 211").count() >= 3
