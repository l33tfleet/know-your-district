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
    HTMX,
    ROOT,
    STATE_DIR,
    Flag,
    card_id,
    client,
    create,
    flag,
    post,
    rows,
)
from tests.regressions.test_wo97_brief_page import parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
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


def test_shipped_flag_is_on_and_the_bare_brief_runs_the_journey(shipped: TestClient) -> None:
    assert features.validate_features()["folders"] == features.Status.ON
    html = shipped.get(BRIEF).text
    saves = parse(html).one("section", class_="case").find_all("div", class_="case-save")
    assert len(saves) == 1
    assert 'action="/folders"' in html
    assert "?preview=1" not in html.split('class="case-save"')[1].split("</div>")[0]

    saved = post(shipped, "/folders", f"case_id={CASE}&chamber=house&district=22")
    assert saved.status_code == 303
    path = saved.headers["location"]
    assert re.fullmatch(r"/f/[0-9a-f]{32}", path)
    page_html = shipped.get(path).text
    card = card_id(shipped, path)
    for action in (f"{path}/cards/{card}/priority", f"{path}/cards/{card}/status"):
        assert f'hx-post="{action}"' in page_html
        assert f'action="{action}"' in page_html
    assert "?preview=1" not in page_html
    done = post(shipped, f"{path}/cards/{card}/status", "status=done")
    assert (done.status_code, done.headers["location"]) == (303, path)
    assert summary_of(shipped, path) == "Priority: Normal. Status: Done."


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


def test_plain_posts_redirect_and_reloading_shows_the_same_values(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    saved = post(client, f"{path}/cards/{card}/priority", "priority=high&reason=Asked+first")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    saved = post(client, f"{path}/cards/{card}/status", "status=planned")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert summary_of(client, path) == "Priority: High (Asked first). Status: Planned."


def test_htmx_gets_the_card_partial_not_a_redirect(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    response = post(client, f"{path}/cards/{card}/status", "status=contacted", HTMX)
    assert response.status_code == 200
    assert "<html" not in response.text
    assert f'id="summary-{card}"' in response.text and "Status: Contacted." in response.text


def test_saving_a_case_twice_keeps_one_card_and_its_state(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    post(client, f"{path}/cards/{card}/status", "status=done")
    saved = post(client, f"{path}/cases", f"case_id={CASE}&chamber=house&district=22")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert client.get(path).text.count('class="folder-card"') == 1
    assert summary_of(client, path) == "Priority: Normal. Status: Done."


def test_outreach_off_keeps_the_saved_state_and_hides_the_figures(flag: Flag) -> None:
    client = flag("on")
    path = create(client)
    features.FEATURES_PATH.write_text('outreach = "off"\nfolders = "on"\n', encoding="utf-8")
    html = client.get(path).text
    assert summary_of(client, path) == "Priority: Normal. Status: Idea."
    assert "B22003" not in html


def test_a_second_folder_cannot_see_or_change_the_first(client: TestClient) -> None:
    first = create(client)
    second = create(client)
    card = card_id(client, first)
    post(client, f"{first}/cards/{card}/status", "status=planned")

    for action, body in (("status", "status=done"), ("priority", "priority=low&reason=Mine")):
        response = post(client, f"{second}/cards/{card}/{action}", body)
        assert response.status_code == 404
    live = client.get(second).text.split('id="live-')[1].split("</div>")[0]
    assert "planned" not in live.lower()
    assert summary_of(client, first) == "Priority: Normal. Status: Planned."
    assert "Mine" not in client.get(first).text


@pytest.mark.parametrize(
    "body", ["priority=high", "priority=high&reason="], ids=["absent", "empty"]
)
def test_priority_with_no_reason_stores_null_and_shows_no_parenthesis(
    client: TestClient, tmp_path: Path, body: str
) -> None:
    path = create(client)
    card = card_id(client, path)
    saved = post(client, f"{path}/cards/{card}/priority", body)
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert rows(tmp_path / "folders.db", "SELECT priority, reason FROM cards") == [("high", None)]
    summary = summary_of(client, path)
    assert summary == "Priority: High. Status: Idea."
    assert "(" not in summary


def test_an_existing_reason_still_shows(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    card = card_id(client, path)
    post(client, f"{path}/cards/{card}/priority", "priority=high&reason=Asked+first")
    assert summary_of(client, path) == "Priority: High (Asked first). Status: Idea."
    assert 'value="Asked first"' in client.get(path).text
    assert rows(tmp_path / "folders.db", "SELECT priority, reason, status FROM cards") == [
        ("high", "Asked first", "idea")
    ]


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


def test_story_step_5_runs_as_written_without_preview(
    page: Page, live_shipped: str, tmp_path: Path
) -> None:
    open_page(page, f"{live_shipped}{BRIEF}", 1440)
    region = page.get_by_role("region", name="SNAP", exact=True)
    region.get_by_role("button", name="Save to folder").click()
    page.wait_for_url("**/f/*")
    page.get_by_role("combobox", name="Priority").select_option(label="High")
    page.get_by_text("Priority: High. Status: Idea.", exact=True).wait_for()
    page.get_by_role("combobox", name="Status").select_option(label="Planned")
    page.get_by_text("Priority: High. Status: Planned.", exact=True).wait_for()
    assert page.get_by_text("Saved").first.is_visible()

    page.reload()
    assert " ".join(page.inner_text(".folder-summary").split()) == (
        "Priority: High. Status: Planned."
    )
    assert page.input_value("select[name=priority]") == "high"
    assert page.input_value("select[name=status]") == "planned"
    assert (tmp_path / STATE_DIR / "folders.db").exists()


def test_browser_saves_priority_and_status_on_change_with_no_click(
    page: Page, live_shipped: str
) -> None:
    open_page(page, f"{live_shipped}{BRIEF}", 1440)
    page.get_by_role("button", name=COPY["save_label"]).click()
    page.wait_for_url("**/f/*")
    assert "preview" not in page.url
    assert axe_problems(page) == []
    url = page.url
    assert page.locator(".folder-card button").count() == 0

    page.select_option("select[name=priority]", "high")
    page.get_by_text("Priority: High. Status: Idea.", exact=True).wait_for()
    page.select_option("select[name=status]", "planned")
    page.get_by_text("Priority: High. Status: Planned.", exact=True).wait_for()
    assert page.url == url  # an htmx partial update, not a page load

    page.fill("input[name=reason]", "Office outreach week")
    page.locator("input[name=reason]").press("Tab")  # leaving the field is its change
    page.get_by_text(
        "Priority: High (Office outreach week). Status: Planned.", exact=True
    ).wait_for()
    # The swap replaces only the summary, so focus stays where Tab put it.
    assert page.evaluate("document.activeElement.name") == "status"

    page.reload()
    summary = " ".join(page.inner_text(".folder-summary").split())
    assert summary == "Priority: High (Office outreach week). Status: Planned."
    assert page.input_value("select[name=priority]") == "high"
    assert page.input_value("input[name=reason]") == "Office outreach week"
    assert page.input_value("select[name=status]") == "planned"
    assert axe_problems(page) == []
