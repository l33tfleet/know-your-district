"""WO82 / WO28: offline evidence for live program-link verification."""

from datetime import date, timedelta
from http.client import HTTPException
from pathlib import Path
from unittest.mock import patch

import pytest

from etl.programs import load_catalog
from etl.programs.__main__ import main
from etl.programs.links import (
    USER_AGENT,
    LinkReport,
    LinkResponse,
    check_catalog,
    check_url,
    http_get,
)

TODAY = date(2026, 10, 28)


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


def test_relative_redirect_requires_final_200() -> None:
    calls: list[str] = []

    def get(url: str, timeout: float) -> LinkResponse:
        assert 0 < timeout <= 10
        calls.append(url)
        return LinkResponse(302, "/final") if len(calls) == 1 else LinkResponse(200)

    check_url("https://agency.gov/start", get=get)
    assert calls == ["https://agency.gov/start", "https://agency.gov/final"]


def test_bad_redirect_is_rejected_before_following() -> None:
    calls: list[str] = []

    def get(url: str, _timeout: float) -> LinkResponse:
        calls.append(url)
        return LinkResponse(302, "https://agency.gov.evil.org/")

    with pytest.raises(ValueError, match="Untrusted URL"):
        check_url("https://agency.gov/", get=get)
    assert calls == ["https://agency.gov/"]


@pytest.mark.parametrize("status", [204, 300, 404, 500])
def test_non_200_fails(status: int) -> None:
    with pytest.raises(ValueError, match=f"HTTP {status}"):
        check_url("https://agency.gov/", get=lambda _u, _t: LinkResponse(status))


def test_missing_location_fails() -> None:
    with pytest.raises(ValueError, match="Missing redirect location"):
        check_url("https://agency.gov/", get=lambda _u, _t: LinkResponse(302))


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


@pytest.mark.parametrize("age", [-1, 0, 29, 30])
def test_date_boundaries_and_every_catalog_url_without_writes(age: int) -> None:
    path = Path("data/programs.yaml")
    original = path.read_bytes()
    programs = [
        p.model_copy(update={"last_verified": TODAY - timedelta(days=age)})
        for p in load_catalog(path)
    ]
    before = [p.model_dump() for p in programs]
    calls: set[str] = set()

    def get(url: str, _timeout: float) -> LinkResponse:
        calls.add(url)
        return LinkResponse(200)

    report = check_catalog(programs, get=get, today=lambda: TODAY)
    failures = report.failures
    assert report.blocked == []
    assert bool(failures) == (age not in (0, 29))
    assert all("verification age" in failure for failure in failures)
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
    assert path.read_bytes() == original


def test_catalog_reports_each_failing_url() -> None:
    programs = load_catalog(Path("data/programs.yaml"))
    report = check_catalog(programs, get=lambda _u, _t: LinkResponse(404), today=lambda: TODAY)
    failures = report.failures
    assert len(failures) == 4 * len(programs)
    assert all("HTTP 404" in failure for failure in failures)


def test_http_facade_does_not_follow_redirects() -> None:
    with patch("etl.programs.links.HTTPSConnection") as connection:
        connection.return_value.getresponse.return_value.status = 302
        connection.return_value.getresponse.return_value.getheader.return_value = "/next"
        assert http_get("https://agency.gov/start?q=1", 10) == LinkResponse(302, "/next")
        connection.assert_called_once_with("agency.gov", timeout=10)
        connection.return_value.request.assert_called_once_with(
            "GET", "/start?q=1", headers={"User-Agent": USER_AGENT}
        )
        connection.return_value.close.assert_called_once()


@pytest.mark.parametrize("failures, expected", [([], 0), (["link failed"], 1)])
def test_cli_exit_status(failures: list[str], expected: int) -> None:
    report = LinkReport(failures=failures, blocked=[])
    with patch("etl.programs.__main__.check_catalog", return_value=report):
        assert main([]) == expected


def test_redirect_controls_are_rejected_before_urljoin_strips_them() -> None:
    with pytest.raises(ValueError, match="Untrusted URL"):
        check_url("https://agency.gov/", get=lambda _u, _t: LinkResponse(302, "/\nnext"))


def test_cli_catalog_read_failure() -> None:
    with patch("etl.programs.__main__.load_catalog", side_effect=OSError("missing")):
        assert main([]) == 1


def test_http_connection_closes_on_timeout() -> None:
    with patch("etl.programs.links.HTTPSConnection") as connection:
        connection.return_value.getresponse.side_effect = TimeoutError("slow headers")
        with pytest.raises(TimeoutError, match="slow headers"):
            http_get("https://agency.gov/", 10)
        connection.return_value.close.assert_called_once()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_final_404_is_failure(status: int) -> None:
    calls: list[str] = []

    def get(url: str, _timeout: float) -> LinkResponse:
        calls.append(url)
        return LinkResponse(status, "/final") if len(calls) == 1 else LinkResponse(404)

    with pytest.raises(ValueError, match="HTTP 404"):
        check_url("https://agency.gov/start", get=get)
    assert calls == ["https://agency.gov/start", "https://agency.gov/final"]


def test_user_agent_identifies_the_checker() -> None:
    assert "KnowYourDistrict-LinkChecker" in USER_AGENT
    assert "district.hawaiitechmentors.org" in USER_AGENT


@pytest.mark.parametrize("status", [401, 403, 429])
def test_bot_wall_statuses_are_blocked_not_verified(status: int) -> None:
    state = check_url("https://www.auw211.org/", get=lambda _u, _t: LinkResponse(status))
    assert state == "blocked"


def test_blocked_after_redirect_is_still_blocked() -> None:
    responses = iter([LinkResponse(301, "/home"), LinkResponse(403)])
    assert check_url("https://agency.gov/", get=lambda _u, _t: next(responses)) == "blocked"


def _bot_wall(url: str, _timeout: float) -> LinkResponse:
    return LinkResponse(403 if "auw211.org" in url else 200)


@pytest.mark.parametrize("age, stale", [(0, False), (29, False), (30, True), (90, True)])
def test_blocked_link_keeps_its_date_and_turns_stale(age: int, stale: bool) -> None:
    path = Path("data/programs.yaml")
    original = path.read_bytes()
    programs = [
        p.model_copy(update={"last_verified": TODAY - timedelta(days=age)})
        for p in load_catalog(path)
    ]
    before = [p.model_dump() for p in programs]
    report = check_catalog(programs, get=_bot_wall, today=lambda: TODAY)
    assert len(report.blocked) == len(programs)
    assert all("referral_url" in b and "not verified" in b for b in report.blocked)
    assert not any("HTTP 403" in f for f in report.failures)
    assert bool(report.failures) == stale
    assert all("verification age" in f for f in report.failures)
    assert [p.model_dump() for p in programs] == before
    assert path.read_bytes() == original


@pytest.mark.parametrize("age, expected", [(4, 0), (30, 1)])
def test_cli_lists_blocked_links_by_name(
    age: int, expected: int, capsys: pytest.CaptureFixture[str]
) -> None:
    programs = [
        p.model_copy(update={"last_verified": TODAY - timedelta(days=age)})
        for p in load_catalog(Path("data/programs.yaml"))
    ]
    report = check_catalog(programs, get=_bot_wall, today=lambda: TODAY)
    with patch("etl.programs.__main__.check_catalog", return_value=report):
        assert main([]) == expected
    out = capsys.readouterr().out
    for program in programs:
        assert f"BLOCKED {program.name} referral_url" in out
    assert "All program URLs return 200" not in out
