"""#348: visible clarification choices must already handle keyboard submission."""

from playwright.sync_api import Page, expect

from app.copy import section_copy
from tests.regressions.test_wo140_agent import RECORDINGS
from tests.regressions.test_wo140_ui import base_url, browser, offline, page, submit

__all__ = ["base_url", "browser", "offline", "page"]


def test_immediate_keyboard_clarification_stays_in_same_document(
    page: Page, base_url: str, offline: list[str]
) -> None:
    url = base_url + "/brief/house/22?preview=1&v=a"
    page.goto(url)
    # Enlarge the activation window without waiting for it: visible response nodes
    # must work immediately, even when htmx's default settle delay is long.
    page.evaluate("window.htmx.config.defaultSettleDelay = 60000; window.wo348SameDocument = true")
    question = RECORDINGS[3].question
    submit(page, question)
    answer = page.get_by_role("region", name="Answer", exact=True)
    expect(answer).to_contain_text(section_copy("ask")["clarify"])
    choice = answer.get_by_role("button", name="Median household income", exact=True)
    expect(choice).to_be_visible()
    choice.focus()
    with page.expect_response(
        lambda response: response.request.method == "POST" and "/brief/house/22/ask" in response.url
    ) as response_info:
        page.keyboard.press("Enter")

    response = response_info.value
    assert response.request.headers.get("hx-request") == "true"
    assert response.status == 200
    expect(answer).to_contain_text("B19013")
    assert page.url == url
    assert page.evaluate("window.wo348SameDocument === true")
    assert offline == [question]
