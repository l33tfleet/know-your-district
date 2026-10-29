"""Read-only link checks. HTTP and calendar time are injectable for offline checks."""

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from pathlib import Path
from time import perf_counter
from typing import Literal
from urllib.parse import urljoin, urlsplit

from pydantic import TypeAdapter

from etl.programs import Program

# Exact hosts only: catalog authors cannot grant domain approval by adding a URL.
OFFICIAL_HOSTS = TypeAdapter(dict[str, str]).validate_json(
    Path(__file__).with_name("official_hosts.json").read_text(encoding="utf-8")
)
TIMEOUT = 10.0
MAX_REDIRECTS = 5
# Bot walls (auw211.org answers 403): the link is not verified, and its date stays as reviewed.
BLOCKED = (401, 403, 429)
USER_AGENT = "KnowYourDistrict-LinkChecker/1.0 (+https://district.hawaiitechmentors.org)"
LinkState = Literal["verified", "blocked"]


@dataclass(frozen=True)
class LinkResponse:
    status: int
    location: str | None = None


@dataclass(frozen=True)
class LinkReport:
    failures: list[str]
    blocked: list[str]


def http_get(url: str, timeout: float) -> LinkResponse:
    """One GET, headers only, no automatic redirects; always close and measure latency.

    Uses the system TLS trust store; reads no credentials or environment variables.
    """
    parts = urlsplit(url)
    connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    connection = connection_type(parts.netloc, timeout=timeout)
    started = perf_counter()
    try:
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        connection.request("GET", path, headers={"User-Agent": USER_AGENT})
        response = connection.getresponse()
        return LinkResponse(response.status, response.getheader("Location"))
    finally:
        connection.close()
        logging.getLogger(__name__).info("GET %s took %.3fs", url, perf_counter() - started)


def _trusted(url: str) -> None:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        valid = (
            not any(ord(c) <= 32 or ord(c) == 127 for c in url)
            and parts.scheme in ("http", "https")
            and parts.username is None
            and parts.password is None
            and (parts.port is None or 1 <= parts.port <= 65535)
            and (
                re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+gov", host)
                or host in OFFICIAL_HOSTS
            )
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"Untrusted URL: {url!r}")


def check_url(url: str, *, get: Callable[[str, float], LinkResponse] = http_get) -> LinkState:
    """Check each hop before sending it; verify only a final 200 within five redirects.

    A final 401/403/429 is "blocked": the site refused automated access. Anything else raises.
    """
    for _ in range(MAX_REDIRECTS + 1):
        _trusted(url)
        try:
            response = get(url, TIMEOUT)
        except (OSError, HTTPException) as exc:
            raise ValueError(f"HTTP request failed: {url}") from exc
        if response.status == 200:
            return "verified"
        if response.status in BLOCKED:
            return "blocked"
        if response.status not in (301, 302, 303, 307, 308):
            raise ValueError(f"HTTP {response.status}: {url}")
        if not response.location:
            raise ValueError(f"Missing redirect location: {url}")
        # urljoin strips some control characters: reject before normalization.
        if any(ord(c) <= 32 or ord(c) == 127 for c in response.location):
            raise ValueError(f"Untrusted URL: {response.location!r}")
        url = urljoin(url, response.location)
    raise ValueError(f"Too many redirects: {url}")


def check_catalog(
    programs: Sequence[Program],
    *,
    get: Callable[[str, float], LinkResponse] = http_get,
    today: Callable[[], date] = lambda: datetime.now(UTC).date(),
) -> LinkReport:
    """Report failures and blocked links; never update last_verified, whatever the result."""
    failures: list[str] = []
    blocked: list[str] = []
    now = today()
    for program in programs:
        age = (now - program.last_verified).days
        if not 0 <= age < 30:
            failures.append(f"{program.name}: verification age {age} days; expected 0–29")
        for field, url in (
            ("official_url", program.official_url),
            ("referral_url", program.referral_url),
            ("agency_guideline.source_url", program.agency_guideline.source_url),
            ("eligibility_proxy.source_url", program.eligibility_proxy.source_url),
        ):
            try:
                if check_url(str(url), get=get) == "blocked":
                    blocked.append(
                        f"{program.name} {field}: {url} refused automated access; not verified"
                    )
            except ValueError as exc:
                failures.append(f"{program.name} {field}: {exc}")
    return LinkReport(failures, blocked)
