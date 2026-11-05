"""Read-only link checks. HTTP and calendar time are injectable for offline checks."""

import re
import sys
from collections.abc import Callable, Iterator, Sequence
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
UrlField = Literal[
    "official_url", "referral_url", "agency_guideline.source_url", "eligibility_proxy.source_url"
]


class LinkCheckError(ValueError):
    """An expected upstream HTTP failure or an explicitly rejected URL."""


@dataclass(frozen=True)
class LinkResponse:
    status: int
    location: str | None = None
    body: bytes | None = None


@dataclass(frozen=True)
class LinkReport:
    failures: list[str]
    blocked: list[str]


def http_get(url: str, timeout: float) -> LinkResponse:
    """One headers-only GET; callers use fetch_url to enforce redirect policy."""
    return _http_get(url, timeout, read_body=False)


def http_content_get(url: str, timeout: float) -> LinkResponse:
    """One content GET, no redirects; system TLS trust, always closed and timed."""
    return _http_get(url, timeout, read_body=True)


def _http_get(url: str, timeout: float, *, read_body: bool) -> LinkResponse:
    _trusted(url)
    parts = urlsplit(url)
    connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    connection = connection_type(parts.netloc, timeout=timeout)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    started = perf_counter()
    try:
        connection.request("GET", path, headers={"User-Agent": USER_AGENT})
        response = connection.getresponse()
        return LinkResponse(
            response.status,
            response.getheader("Location"),
            response.read() if read_body and response.status == 200 else None,
        )
    finally:
        connection.close()
        print(f"GET {url}: {perf_counter() - started:.3f}s", file=sys.stderr)


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
        raise LinkCheckError(f"Untrusted URL: {url!r}")


def fetch_url(url: str, *, get: Callable[[str, float], LinkResponse] = http_get) -> LinkResponse:
    """Check each hop before sending it; verify only a final 200 within five redirects.

    A final 401/403/429 is "blocked": the site refused automated access. Anything else raises.
    """
    for _ in range(MAX_REDIRECTS + 1):
        _trusted(url)
        try:
            response = get(url, TIMEOUT)
        except (OSError, HTTPException) as exc:
            raise LinkCheckError(f"HTTP request failed: {url}") from exc
        if response.status == 200:
            return response
        if response.status in BLOCKED:
            return response
        if response.status not in (301, 302, 303, 307, 308):
            raise LinkCheckError(f"HTTP {response.status}: {url}")
        if not response.location:
            raise LinkCheckError(f"Missing redirect location: {url}")
        # urljoin strips some control characters: reject before normalization.
        if any(ord(c) <= 32 or ord(c) == 127 for c in response.location):
            raise LinkCheckError(f"Untrusted URL: {response.location!r}")
        try:
            url = urljoin(url, response.location)
        except ValueError as exc:
            raise LinkCheckError(f"Untrusted URL: {response.location!r}") from exc
    raise LinkCheckError(f"Too many redirects: {url}")


def check_url(url: str, *, get: Callable[[str, float], LinkResponse] = http_get) -> LinkState:
    """Verify links through the same trusted-host and redirect policy as content hashes."""
    return "verified" if fetch_url(url, get=get).status == 200 else "blocked"


def iter_program_urls(program: Program) -> Iterator[tuple[UrlField, str]]:
    """All URL fields accepted by load_catalog, including distinct nested sources.

    #211 acceptance scope: optional enrichment is deferred until catalog integration.
    Keep field occurrences even when several fields reference the same URL.
    """
    yield "official_url", str(program.official_url)
    yield "referral_url", program.referral_url
    yield "agency_guideline.source_url", str(program.agency_guideline.source_url)
    yield "eligibility_proxy.source_url", str(program.eligibility_proxy.source_url)


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
        for field, url in iter_program_urls(program):
            try:
                if check_url(str(url), get=get) == "blocked":
                    blocked.append(
                        f"{program.name} {field}: {url} refused automated access; not verified"
                    )
            except LinkCheckError as exc:
                failures.append(f"{program.name} {field}: {exc}")
    return LinkReport(failures, blocked)
