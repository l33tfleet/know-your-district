"""Smoke-test a running app: `python scripts/smoke.py BASE_URL` (exit 1 on failure)."""

import sys
import urllib.error
import urllib.request

CHECKS = [("/healthz", 200)]


def check(base_url: str) -> list[str]:
    failures: list[str] = []
    for path, expected in CHECKS:
        url = base_url.rstrip("/") + path
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                status = int(response.status)
        except urllib.error.HTTPError as err:
            status = err.code
        except OSError as err:
            failures.append(f"GET {url}: {err}")
            continue
        if status != expected:
            failures.append(f"GET {url}: expected {expected}, got {status}")
        else:
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
