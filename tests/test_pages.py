"""Characterization tests of the rendered pages (operator-owned).

These pin what the pages look like today so an unintended change shows up.
Agents add new tests under tests/regressions/ instead of editing this file.
"""

from fastapi.testclient import TestClient

from app.main import HTMX_VERSION, app

client = TestClient(app)


def test_healthz_body() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_home_page_shell() -> None:
    html = client.get("/").text
    assert html.startswith("<!doctype html>")
    assert '<html lang="en">' in html
    assert '<meta charset="utf-8">' in html
    assert "<title>Know Your District</title>" in html
    assert "<h1>Know Your District</h1>" in html


def test_home_page_spells_hawaii_with_okina() -> None:
    html = client.get("/").text
    assert "Hawaiʻi" in html
    assert "Hawai'i" not in html
    assert f"Hawai{chr(0x2018)}i" not in html  # left single quotation mark, a common wrong ʻokina
    assert "Hawaii " not in html


def test_home_page_loads_vendored_htmx_2_only() -> None:
    html = client.get("/").text
    assert HTMX_VERSION.startswith("2.0.")
    assert f'<script src="/static/vendor/htmx-{HTMX_VERSION}.min.js" defer></script>' in html
    assert "unpkg" not in html
    assert "cdn" not in html.lower()


def test_home_page_says_programs_may_help() -> None:
    html = client.get("/").text
    assert "may help" in html
    assert "qualify" not in html


def test_stylesheet_is_served() -> None:
    response = client.get("/static/site.css")
    assert response.status_code == 200
    assert "@media print" in response.text


def test_unknown_page_is_404() -> None:
    assert client.get("/no-such-page").status_code == 404
