"""WO82 / WO28: offline evidence for live program-link verification."""

from datetime import date, timedelta
from http.client import HTTPException
from pathlib import Path
from unittest.mock import patch

import pytest

from etl.programs import Program, load_catalog
from etl.programs.__main__ import main
from etl.programs.links import USER_AGENT, LinkResponse, check_catalog, check_url, http_get

TODAY = date(2026, 10, 28)
CATALOG = Path("data/programs.yaml")


def _aged(age: int) -> list[Program]:
    return [
        p.model_copy(update={"last_verified": TODAY - timedelta(days=age)})
        for p in load_catalog(CATALOG)
    ]


@pytest.mark.parametrize(
    "url", ["https://agency.gov/a", "https://sub.agency.gov/a", "https://www.auw211.org/"]
)
def test_final_200_and_reviewed_hosts(url: str) -> None:
    assert check_url(url, get=lambda _url, _timeout: LinkResponse(200)) == "verified"


@pytest.mark.parametrize(
    "url",
    [
        "https://agency.gov.evil.org/",
        "https://evil.org/agency.gov",
        "https://notgov/",
        "https://agency.gov@evil.org/",
        "https://sub.auw211.org/",
        "ftp://agency.gov/",
        "https://user@agency.gov/",
        "https://agency.gov:bad/",
        "https://agency.gov:0/",
        "https://agency.gov:65536/",
        "https://[broken/",
        "https://agency.gov/\nx",
    ],
)
def test_bad_urls_never_requested(url: str) -> None:
    def forbidden(_url: str, _timeout: float) -> LinkResponse:
        pytest.fail("untrusted URL reached HTTP")

    with pytest.raises(ValueError, match="Untrusted URL"):
        check_url(url, get=forbidden)


@pytest.mark.parametrize("redirect", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("final", [200, 404])
def test_relative_redirect_requires_final_200(redirect: int, final: int) -> None:
    calls: list[str] = []

    def get(url: str, timeout: float) -> LinkResponse:
        assert 0 < timeout <= 10
        calls.append(url)
        return LinkResponse(redirect, "/final") if len(calls) == 1 else LinkResponse(final)

    if final == 200:
        assert check_url("https://agency.gov/start", get=get) == "verified"
    else:
        with pytest.raises(ValueError, match="HTTP 404"):
            check_url("https://agency.gov/start", get=get)
    assert calls == ["https://agency.gov/start", "https://agency.gov/final"]


@pytest.mark.parametrize(
    "response, message",
    [
        (LinkResponse(302, "https://agency.gov.evil.org/"), "Untrusted URL"),
        (LinkResponse(302, "/\nnext"), "Untrusted URL"),  # rejected before urljoin strips it
        (LinkResponse(302), "Missing redirect location"),
        (LinkResponse(204), "HTTP 204"),
        (LinkResponse(300), "HTTP 300"),
        (LinkResponse(404), "HTTP 404"),
        (LinkResponse(500), "HTTP 500"),
    ],
)
def test_bad_response_fails_without_following(response: LinkResponse, message: str) -> None:
    calls: list[str] = []

    def get(url: str, _timeout: float) -> LinkResponse:
        calls.append(url)
        return response

    with pytest.raises(ValueError, match=message):
        check_url("https://agency.gov/", get=get)
    assert calls == ["https://agency.gov/"]


def test_redirect_loop_is_bounded() -> None:
    calls: list[str] = []

    def get(url: str, _timeout: float) -> LinkResponse:
        calls.append(url)
        return LinkResponse(301, "/loop")

    with pytest.raises(ValueError, match="Too many redirects"):
        check_url("https://agency.gov/", get=get)
    assert len(calls) == 6


@pytest.mark.parametrize(
    "error", [TimeoutError("slow"), OSError("offline"), HTTPException("bad headers")]
)
def test_network_failure_is_contained(error: OSError | HTTPException) -> None:
    def get(_url: str, _timeout: float) -> LinkResponse:
        raise error

    with pytest.raises(ValueError, match="HTTP request failed"):
        check_url("https://agency.gov/", get=get)


def test_http_facade_identifies_itself_and_does_not_follow_redirects() -> None:
    assert "KnowYourDistrict-LinkChecker" in USER_AGENT
    assert "district.hawaiitechmentors.org" in USER_AGENT
    with patch("etl.programs.links.HTTPSConnection") as connection:
        connection.return_value.getresponse.return_value.status = 302
        connection.return_value.getresponse.return_value.getheader.return_value = "/next"
        assert http_get("https://agency.gov/start?q=1", 10) == LinkResponse(302, "/next")
        connection.assert_called_once_with("agency.gov", timeout=10)
        connection.return_value.request.assert_called_once_with(
            "GET", "/start?q=1", headers={"User-Agent": USER_AGENT}
        )
        connection.return_value.close.assert_called_once()


def test_http_connection_closes_on_timeout() -> None:
    with patch("etl.programs.links.HTTPSConnection") as connection:
        connection.return_value.getresponse.side_effect = TimeoutError("slow headers")
        with pytest.raises(TimeoutError, match="slow headers"):
            http_get("https://agency.gov/", 10)
        connection.return_value.close.assert_called_once()


@pytest.mark.parametrize("hops", [[401], [403], [429], [301, 403]])
def test_bot_wall_statuses_are_blocked_not_verified(hops: list[int]) -> None:
    responses = iter(LinkResponse(status, "/home") for status in hops)
    assert check_url("https://www.auw211.org/", get=lambda _u, _t: next(responses)) == "blocked"


@pytest.mark.parametrize("age, stale", [(-1, True), (0, False), (29, False), (30, True)])
def test_every_url_checked_blocked_date_kept_and_turns_stale(age: int, stale: bool) -> None:
    original = CATALOG.read_bytes()
    programs = _aged(age)
    before = [p.model_dump() for p in programs]
    calls: set[str] = set()

    def bot_wall(url: str, _timeout: float) -> LinkResponse:
        calls.add(url)
        return LinkResponse(403 if "auw211.org" in url else 200)

    report = check_catalog(programs, get=bot_wall, today=lambda: TODAY)
    assert len(report.blocked) == len(programs)
    assert all("referral_url" in b and "not verified" in b for b in report.blocked)
    assert bool(report.failures) == stale
    assert all("verification age" in f for f in report.failures)
    assert calls == {
        str(url)
        for p in programs
        for url in (
            p.official_url,
            p.referral_url,
            p.agency_guideline.source_url,
            p.eligibility_proxy.source_url,
        )
    }
    assert [p.model_dump() for p in programs] == before
    assert CATALOG.read_bytes() == original


def test_catalog_reports_each_failing_url() -> None:
    report = check_catalog(_aged(0), get=lambda _u, _t: LinkResponse(404), today=lambda: TODAY)
    assert len(report.failures) == 4 * len(_aged(0))
    assert all("HTTP 404" in failure for failure in report.failures)


@pytest.mark.parametrize("age, expected", [(4, 0), (30, 1)])
def test_cli_exit_status_lists_blocked_links_by_name(
    age: int, expected: int, capsys: pytest.CaptureFixture[str]
) -> None:
    programs = _aged(age)
    report = check_catalog(
        programs,
        get=lambda u, _t: LinkResponse(403 if "auw211.org" in u else 200),
        today=lambda: TODAY,
    )
    with patch("etl.programs.__main__.check_catalog", return_value=report):
        assert main([]) == expected
    out = capsys.readouterr().out
    for program in programs:
        assert f"BLOCKED {program.name} referral_url" in out


def test_cli_catalog_read_failure() -> None:
    with patch("etl.programs.__main__.load_catalog", side_effect=OSError("missing")):
        assert main([]) == 1
