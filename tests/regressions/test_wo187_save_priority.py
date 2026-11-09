"""WO187: saving priority and status, with the plain folder wording.

Each test here is a copy of a superseded test in test_wo_step5_save_priority.py, changed only where it pinned
the old words ("Priority: X. Status: Y." is now "Priority is X. Status is Y."; the note
hint and confirmation now say "groups of people, not one resident"). Every check of
behaviour, storage, isolation, focus and accessibility is kept as it was.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app import features
from tests.regressions.test_journey_folder_save import (
    BRIEF,
    CASE,
    COPY,
    HTMX,
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
from tests.regressions.test_wo_step5_save_priority import live_shipped, shipped, summary_of

__all__ = [
    "BRIEF",
    "CASE",
    "COPY",
    "HTMX",
    "STATE_DIR",
    "Flag",
    "axe_problems",
    "base_url",
    "browser",
    "card_id",
    "client",
    "config",
    "create",
    "flag",
    "live_shipped",
    "open_page",
    "page",
    "parse",
    "post",
    "rows",
    "shipped",
    "shipped_facts",
    "summary_of",
]


# Replaces test_wo_step5_save_priority.py::test_shipped_flag_is_on_and_the_bare_brief_runs_the_journey (wording only, #187).
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
    assert summary_of(shipped, path) == "Priority is Normal. Status is Done."


# Replaces test_wo_step5_save_priority.py::test_plain_posts_redirect_and_reloading_shows_the_same_values (wording only, #187).
def test_plain_posts_redirect_and_reloading_shows_the_same_values(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    saved = post(client, f"{path}/cards/{card}/priority", "priority=high&reason=Asked+first")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    saved = post(client, f"{path}/cards/{card}/status", "status=planned")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert summary_of(client, path) == "Priority is High (Asked first). Status is Planned."


# Replaces test_wo_step5_save_priority.py::test_htmx_gets_the_card_partial_not_a_redirect (wording only, #187).
def test_htmx_gets_the_card_partial_not_a_redirect(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    response = post(client, f"{path}/cards/{card}/status", "status=contacted", HTMX)
    assert response.status_code == 200
    assert "<html" not in response.text
    assert f'id="summary-{card}"' in response.text and "Status is Contacted." in response.text


# Replaces test_wo_step5_save_priority.py::test_saving_a_case_twice_keeps_one_card_and_its_state (wording only, #187).
def test_saving_a_case_twice_keeps_one_card_and_its_state(client: TestClient) -> None:
    path = create(client)
    card = card_id(client, path)
    post(client, f"{path}/cards/{card}/status", "status=done")
    saved = post(client, f"{path}/cases", f"case_id={CASE}&chamber=house&district=22")
    assert (saved.status_code, saved.headers["location"]) == (303, path)
    assert client.get(path).text.count('class="folder-card"') == 1
    assert summary_of(client, path) == "Priority is Normal. Status is Done."


# Replaces test_wo_step5_save_priority.py::test_outreach_off_keeps_the_saved_state_and_hides_the_figures (wording only, #187).
def test_outreach_off_keeps_the_saved_state_and_hides_the_figures(flag: Flag) -> None:
    client = flag("on")
    path = create(client)
    features.FEATURES_PATH.write_text('outreach = "off"\nfolders = "on"\n', encoding="utf-8")
    html = client.get(path).text
    assert summary_of(client, path) == "Priority is Normal. Status is Idea."
    assert "B22003" not in html


# Replaces test_wo_step5_save_priority.py::test_a_second_folder_cannot_see_or_change_the_first (wording only, #187).
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
    assert summary_of(client, first) == "Priority is Normal. Status is Planned."
    assert "Mine" not in client.get(first).text


# Replaces test_wo_step5_save_priority.py::test_priority_with_no_reason_stores_null_and_shows_no_parenthesis (wording only, #187).
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
    assert summary == "Priority is High. Status is Idea."
    assert "(" not in summary


# Replaces test_wo_step5_save_priority.py::test_an_existing_reason_still_shows (wording only, #187).
def test_an_existing_reason_still_shows(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    card = card_id(client, path)
    post(client, f"{path}/cards/{card}/priority", "priority=high&reason=Asked+first")
    assert summary_of(client, path) == "Priority is High (Asked first). Status is Idea."
    assert 'value="Asked first"' in client.get(path).text
    assert rows(tmp_path / "folders.db", "SELECT priority, reason, status FROM cards") == [
        ("high", "Asked first", "idea")
    ]


# Replaces test_wo_step5_save_priority.py::test_story_step_5_runs_as_written_without_preview (wording only, #187).
def test_story_step_5_runs_as_written_without_preview(
    page: Page, live_shipped: str, tmp_path: Path
) -> None:
    open_page(page, f"{live_shipped}{BRIEF}", 1440)
    region = page.get_by_role("region", name="SNAP", exact=True)
    region.get_by_role("button", name="Save to folder").click()
    page.wait_for_url("**/f/*")
    page.get_by_role("combobox", name="Priority").select_option(label="High")
    page.get_by_text("Priority is High. Status is Idea.", exact=True).wait_for()
    page.get_by_role("combobox", name="Status").select_option(label="Planned")
    page.get_by_text("Priority is High. Status is Planned.", exact=True).wait_for()
    assert page.get_by_text("Saved").first.is_visible()

    page.reload()
    assert " ".join(page.inner_text(".folder-summary").split()) == (
        "Priority is High. Status is Planned."
    )
    assert page.input_value("select[name=priority]") == "high"
    assert page.input_value("select[name=status]") == "planned"
    assert (tmp_path / STATE_DIR / "folders.db").exists()


# Replaces test_wo_step5_save_priority.py::test_browser_saves_priority_and_status_on_change_with_no_click (wording only, #187).
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
    page.get_by_text("Priority is High. Status is Idea.", exact=True).wait_for()
    page.select_option("select[name=status]", "planned")
    page.get_by_text("Priority is High. Status is Planned.", exact=True).wait_for()
    assert page.url == url  # an htmx partial update, not a page load

    page.fill("input[name=reason]", "Office outreach week")
    page.locator("input[name=reason]").press("Tab")  # leaving the field is its change
    page.get_by_text(
        "Priority is High (Office outreach week). Status is Planned.", exact=True
    ).wait_for()
    # The swap replaces only the summary, so focus stays where Tab put it.
    assert page.evaluate("document.activeElement.name") == "status"

    page.reload()
    summary = " ".join(page.inner_text(".folder-summary").split())
    assert summary == "Priority is High (Office outreach week). Status is Planned."
    assert page.input_value("select[name=priority]") == "high"
    assert page.input_value("input[name=reason]") == "Office outreach week"
    assert page.input_value("select[name=status]") == "planned"
    assert axe_problems(page) == []
