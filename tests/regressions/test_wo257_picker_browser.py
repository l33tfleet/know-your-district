"""WO257: the one-control picker in a real browser.

Replaces these `test_wo122_browser_checks.py` tests, which drove the old two-select picker:
`test_picker_opens_brief_without_full_reload`, `test_brief_reached_by_picker_passes_the_same_checks`,
`test_planted_full_reload_fails_reload_check` and
`test_planted_wrong_title_after_picker_fails_reload_check`. The same checks run on the combined
`#chamber` select, plus the work order's own: after Senate 7 → Open the brief → Back the picker
holds one consistent choice, it works with JavaScript off, and it takes Tab and arrow keys.
"""

import re

import pytest
from playwright.sync_api import Browser, Page

from tests.regressions.test_wo122_browser_checks import (
    WIDTHS,
    axe_problems,
    base_url,
    browser,
    keyboard_problems,
    open_page,
    page,
    page_text,
    spelling_problems,
)

# Reuse the WO122 server and Chromium fixtures without modifying their source.
__all__ = ["base_url", "browser", "page"]

CHOICE = re.compile(r"^(house|senate)-([1-9][0-9]*)$")


def reload_problems(page: Page, base_url: str) -> list[str]:
    """Choose House 22 in the picker on `/`; the brief must arrive without a page reload."""
    page.evaluate("window.kydSameDocument = true")
    page.select_option("#chamber", "house-22")
    page.get_by_role("button", name="Open the brief").click()
    page.wait_for_url(f"{base_url}/brief/house/22")
    page.locator("h1", has_text="Hawaiʻi State House District 22").wait_for()
    problems: list[str] = []
    if not page.evaluate("window.kydSameDocument === true"):
        problems.append("choosing a district reloaded the whole page")
    if page.title() != "Hawaiʻi State House District 22 · Know Your District":
        problems.append(f"page title after the picker is {page.title()!r}")
    return problems


def picker_choice(page: Page) -> tuple[str, str]:
    """The picker's one choice as (chamber, number); fails if the form holds anything else."""
    assert page.locator("form.picker select").count() == 1
    value = page.input_value("#chamber")
    found = CHOICE.match(value)
    assert found, value
    return found.group(1), found.group(2)


@pytest.mark.parametrize("width", WIDTHS)
def test_picker_opens_brief_without_full_reload(page: Page, base_url: str, width: int) -> None:
    open_page(page, base_url + "/", width)
    assert reload_problems(page, base_url) == []


def test_brief_reached_by_picker_passes_the_same_checks(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 390)
    assert reload_problems(page, base_url) == []
    assert axe_problems(page) == []
    assert spelling_problems(page_text(page)) == []
    assert keyboard_problems(page) == []


def test_planted_full_reload_fails_reload_check(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    # A copy of the form that htmx has not processed submits the browser's way: a full reload.
    page.evaluate(
        "(() => { const f = document.querySelector('form.picker');"
        " const plain = f.cloneNode(true);"
        " for (const e of [plain, ...plain.querySelectorAll('*')])"
        "   for (const a of [...e.attributes]) if (a.name.startsWith('hx-')) e.removeAttribute(a.name);"
        " f.replaceWith(plain); })()"
    )
    assert reload_problems(page, base_url) == ["choosing a district reloaded the whole page"]


def test_planted_wrong_title_after_picker_fails_reload_check(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    # The brief still arrives without a reload, but the swapped-in response has the wrong title.
    page.evaluate(
        "document.addEventListener('htmx:beforeSwap', e => {"
        " e.detail.serverResponse = e.detail.serverResponse.replace("
        "   '<title>Hawaiʻi State House District 22', '<title>Wrong District 22'); })"
    )
    assert reload_problems(page, base_url) == [
        "page title after the picker is 'Wrong District 22 · Know Your District'"
    ]


def test_choosing_makes_no_request_until_submit(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.select_option("#chamber", "senate-7")
    page.select_option("#chamber", "house-40")
    page.wait_for_timeout(300)
    assert requests == []


def test_back_after_opening_senate_7_leaves_one_consistent_choice(
    page: Page, base_url: str
) -> None:
    open_page(page, base_url + "/", 1440)
    page.select_option("#chamber", "senate-7")
    page.get_by_role("button", name="Open the brief").click()
    page.wait_for_url(f"{base_url}/brief/senate/7")
    page.locator("h1", has_text="Senate District 7").wait_for()
    page.go_back()
    page.wait_for_url(f"{base_url}/")
    page.locator("form.picker").wait_for()
    chamber, number = picker_choice(page)
    # Whatever the picker shows after Back is exactly what it opens.
    page.get_by_role("button", name="Open the brief").click()
    page.wait_for_url(f"{base_url}/brief/{chamber}/{number}")
    page.locator("h1", has_text=f"{chamber.capitalize()} District {number}").wait_for()


def test_picker_works_with_javascript_disabled(browser: Browser, base_url: str) -> None:
    context = browser.new_context(java_script_enabled=False)
    context.set_default_timeout(10_000)
    try:
        page = context.new_page()
        page.goto(base_url + "/")
        page.select_option("#chamber", "senate-7")
        page.get_by_role("button", name="Open the brief").click()
        page.wait_for_url(f"{base_url}/brief/senate/7")
        page.locator("h1", has_text="Senate District 7").wait_for()
    finally:
        context.close()


def test_picker_is_reached_by_tab_and_chosen_with_arrow_keys(page: Page, base_url: str) -> None:
    open_page(page, base_url + "/", 1440)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    for _ in range(50):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.id") == "chamber":
            break
    else:
        pytest.fail("the picker is not reachable by Tab")
    assert page.input_value("#chamber") == "house-1"
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    assert page.input_value("#chamber") == "house-3"
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    page.wait_for_url(f"{base_url}/brief/house/3")
