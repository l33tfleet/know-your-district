"""WO #108: an unknown path returns a styled HTML 404 page inside the site
layout with a link home, not raw JSON `{"detail":"Not Found"}`."""

from html.parser import HTMLParser

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app


class PageShape(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h1_count = 0
        self.header_count = 0
        self.footer_count = 0
        self.links: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            self.h1_count += 1
        elif tag == "header":
            self.header_count += 1
        elif tag == "footer":
            self.footer_count += 1
        elif tag == "a":
            self.links.extend(v for k, v in attrs if k == "href" and v is not None)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def parse(html: str) -> PageShape:
    shape = PageShape()
    shape.feed(html)
    return shape


@pytest.mark.parametrize("path", ["/district/house/1", "/no-such-page"])
def test_unknown_path_returns_html_404(path: str) -> None:
    response = TestClient(app).get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert '"detail"' not in response.text


@pytest.mark.parametrize("path", ["/district/house/1", "/no-such-page"])
def test_404_page_has_layout_one_h1_and_home_link(path: str) -> None:
    shape = parse(TestClient(app).get(path).text)
    assert shape.header_count == 1
    assert shape.footer_count == 1
    assert shape.h1_count == 1
    # A link to / besides the site name in the header.
    assert shape.links.count("/") >= 2
    assert "doesn" in "".join(shape.text).lower()


def test_404_page_uses_okina_not_apostrophe() -> None:
    text = TestClient(app).get("/no-such-page").text
    assert "Hawai\N{MODIFIER LETTER TURNED COMMA}i" in text
    for quote in ("'", "\N{LEFT SINGLE QUOTATION MARK}", "\N{RIGHT SINGLE QUOTATION MARK}"):
        assert f"Hawai{quote}i" not in text


def test_route_raising_http_404_gets_the_same_page() -> None:
    def missing() -> None:
        raise HTTPException(status_code=404)

    route = APIRoute("/__wo108_missing", missing)
    app.router.routes.append(route)
    try:
        response = TestClient(app).get("/__wo108_missing")
    finally:
        app.router.routes.remove(route)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "/" in parse(response.text).links


def test_healthz_still_returns_json_ok() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
