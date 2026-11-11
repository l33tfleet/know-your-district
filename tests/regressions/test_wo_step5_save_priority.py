"""#347 (journey step 5, part 2): folders ship on, and the shown choices read High, Planned.

The shipped `features.toml` turns `folders` on, so the bare brief carries the save form and the
journey runs without `?preview=1`. The option labels and the summary capitalise the words; the
stored values stay lower-case (`store.Priority`/`Status` unchanged).

Replaces, at least as strictly, six tests of `test_journey_folder_save.py` (#288), one of
`test_journey_opening_case.py` (#286) and three of `test_wo_step5_save_on_change.py` (#346) that
pinned the preview-only brief or the lower-case summary words.
"""

import importlib
import re
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from playwright.sync_api import Page

import app.copy
from app import features
from app.copy import load_copy
from app.folders import store
from app.page_state import page_state
from tests.regressions.test_journey_folder_save import (
    BRIEF,
    CASE,
    COPY,
    HTMX,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    ROOT,
    STATE_DIR,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
    Flag,
    card_id,
    client,
    create,
    flag,
    post,
    rows,  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
)
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

# Reuse the #288 and WO122 fixtures unchanged.
__all__ = ["base_url", "browser", "client", "config", "flag", "page", "shipped_facts"]

CASE_COPY: dict[str, Any] = yaml.safe_load(app.copy.COPY_PATH.read_text(encoding="utf-8"))[
    "sections"
]["case"]


def summary_of(client: TestClient, path: str) -> str:
    return " ".join(parse(client.get(path).text).one("p", class_="folder-summary").text.split())


@pytest.fixture
def shipped(flag: Flag, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client on the committed `features.toml`, with the store file outside the checkout."""
    client = flag("on")
    monkeypatch.setattr(features, "FEATURES_PATH", ROOT / "features.toml")
    return client


# --- the copy ---


def test_choices_show_capitalised_and_store_lower_case() -> None:
    words = load_copy()["folders"]
    assert words["priorities"] == {"high": "High", "normal": "Normal", "low": "Low"}
    assert words["statuses"] == {
        "idea": "Idea",
        "contacted": "Contacted",
        "planned": "Planned",
        "done": "Done",
    }
    assert tuple(words["priorities"]) == get_args(store.Priority)
    assert tuple(words["statuses"]) == get_args(store.Status)


def test_options_keep_lower_case_values_with_capitalised_labels(client: TestClient) -> None:
    html = client.get(create(client)).text
    assert re.findall(r'<option value="(\w+)"(?: selected)?>(\w+)</option>', html) == [
        ("high", "High"),
        ("normal", "Normal"),
        ("low", "Low"),
        ("idea", "Idea"),
        ("contacted", "Contacted"),
        ("planned", "Planned"),
        ("done", "Done"),
    ]


# --- the shipped flag ---


def test_preview_still_carries_through_the_journey_when_the_flag_is_preview(flag: Flag) -> None:
    client = flag("preview")
    assert "case-save" not in client.get(BRIEF).text
    html = client.get(f"{BRIEF}?preview=1").text
    assert 'action="/folders?preview=1"' in html
    saved = post(client, "/folders?preview=1", f"case_id={CASE}&chamber=house&district=22")
    path = saved.headers["location"]
    assert path.endswith("?preview=1")
    page_html = client.get(path).text
    bare = path.removesuffix("?preview=1")
    card = card_id(client, path)
    assert f'href="{path}"' in page_html
    for action in (f"{bare}/cards/{card}/priority", f"{bare}/cards/{card}/status"):
        assert f'hx-post="{action}?preview=1"' in page_html
        assert f'action="{action}?preview=1"' in page_html
    done = post(client, f"{bare}/cards/{card}/status?preview=1", "status=done")
    assert done.headers["location"] == path
    assert client.get(bare).status_code == 404


def test_the_brief_has_exactly_one_save_slot_and_the_template_renders_only_a_passed_control(
    shipped: TestClient,
) -> None:
    document = parse(shipped.get(BRIEF).text)
    saves = document.find_all("div", class_="case-save")
    assert len(saves) == 1
    form = saves[0].one("form")
    assert (form.attrs["method"], form.attrs["action"]) == ("post", "/folders")
    assert form.one("button").text == COPY["save_label"]

    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"])
    )
    template = env.get_template("sections/15-case.html")
    module = importlib.import_module("app.sections.15_case")
    state = page_state("house", "22")
    assert state is not None
    section: dict[str, object] = module.case_card(state, CASE)
    plain = template.render(section=section, copy=CASE_COPY, state=state)
    assert "case-save" not in plain
    slot = Markup("<button>Save to folder</button>")
    saved = template.render(section=section | {"save_control": slot}, copy=CASE_COPY, state=state)
    assert parse(saved).one("div", class_="case-save").one("button").text == "Save to folder"


# --- the summary words ---


def test_refusals_still_name_the_stored_lower_case_values(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    bad = post(client, f"{path}/cards/{card}/priority", "priority=High")
    assert bad.status_code == 422
    assert "high, normal, low" in bad.json()["detail"]
    bad = post(client, f"{path}/cards/{card}/status", "status=Planned")
    assert bad.status_code == 422
    assert "idea, contacted, planned, done" in bad.json()["detail"]


# --- the browser ---


@pytest.fixture
def live_shipped(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shipped_facts: str
) -> str:
    """The in-process server on the committed `features.toml`, with no store setting at all."""
    monkeypatch.setattr(features, "FEATURES_PATH", ROOT / "features.toml")
    monkeypatch.delenv("KYD_FOLDERS_DB", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return shipped_facts


def test_the_brief_has_exactly_one_region_named_snap(page: Page, live_shipped: str) -> None:
    open_page(page, f"{live_shipped}{BRIEF}", 1440)
    region = page.get_by_role("region", name="SNAP", exact=True)
    assert region.count() == 1
    assert region.get_by_role("button", name=COPY["save_label"]).count() == 1
