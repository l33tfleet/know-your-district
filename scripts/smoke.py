"""Smoke-test a running app: `python scripts/smoke.py BASE_URL` (exit 1 on failure)."""

import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser

CHECKS = [
    ("/healthz", 200),
    ("/", 200),
    ("/brief/house/22", 200),
    ("/brief/senate/1", 200),
    ("/static/vendor/htmx-2.0.11.min.js", 200),
]


class HouseFigure(HTMLParser):
    """Check the population reading and its citation within the same figure.

    The page also has statewide readings and a vintage headline; neither proves
    that House 22's facts made it into the build.
    """

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.reading = False
        self.citation = False
        self.field = ""
        self.value = False
        self.table = ""
        self.vintage = ""
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif attributes.get("data-figure") == "population":
                self.depth = 1
                self.value = False
                self.table = self.vintage = ""
        if not self.depth:
            return
        district = attributes.get("data-geography") == "house:15:022:2022"
        if tag == "p":
            self.reading = district
        if tag == "dl":
            self.citation = district
        if tag == "dd":
            self.field = attributes.get("data-field") or ""
        if tag == "data" and self.reading and "value" in (attributes.get("class") or "").split():
            self.value = bool((attributes.get("value") or "").strip())

    def handle_data(self, data: str) -> None:
        if self.depth and self.citation:
            if self.field == "table_id":
                self.table += data
            elif self.field == "vintage":
                self.vintage += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self.reading = False
        if tag == "dl":
            self.citation = False
        if tag == "dd":
            self.field = ""
        if tag == "div" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.found |= (
                    self.value
                    and self.table.strip() == "B01003"
                    and self.vintage.strip() == "2020–2024"
                )


def check(base_url: str) -> list[str]:
    failures: list[str] = []
    for path, expected in CHECKS:
        url = base_url.rstrip("/") + path
        body = b""
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                status = int(response.status)
                body = response.read() if path == "/brief/house/22" else b""
        except urllib.error.HTTPError as err:
            status = err.code
        except OSError as err:
            failures.append(f"GET {url}: {err}")
            continue
        if status != expected:
            failures.append(f"GET {url}: expected {expected}, got {status}")
        else:
            if path == "/brief/house/22":
                figure = HouseFigure()
                figure.feed(body.decode("utf-8", errors="replace"))
                if not figure.found:
                    failures.append(f"GET {url}: missing cited House 22 figure (B01003, 2020–2024)")
                    continue
            print(f"ok  GET {url} -> {status}")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: smoke.py BASE_URL", file=sys.stderr)
        return 2
    failures = check(argv[1])
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
