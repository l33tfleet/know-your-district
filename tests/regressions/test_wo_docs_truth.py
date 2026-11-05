"""WO #269: judge entry point and privacy claims describe the implemented brief."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def document(path: str) -> str:
    """Ignore Markdown wrapping when checking documentation coverage."""
    return " ".join((ROOT / path).read_text(encoding="utf-8").split()).lower()


def test_readme_replaces_scaffold_with_implemented_brief() -> None:
    readme = document("README.md")
    assert "status: scaffold" not in readme
    assert "placeholder home page" not in readme
    assert "a chat bar edits the brief" not in readme
    assert "from the data work orders on" not in readme
    assert "76" in readme and "51" in readme and "25" in readme
    assert "https://district.hawaiitechmentors.org" in readme


@pytest.mark.parametrize(
    "topic",
    [
        "total population",
        "65",
        "median household income",
        "margin of error",
        "reliable",
        "moderate",
        "use with caution",
        "table id",
        "vintage",
        "geography",
        "method",
        "print",
        "uv sync",
        "make run",
        "make check",
        "make smoke",
        "2020–2024",
        "b01003",
        "dp05",
        "b19013",
        "b22003",
        "data/programs.yaml",
        "data/snap/referrals.json",
    ],
)
def test_readme_covers_current_features_and_sources(topic: str) -> None:
    assert topic in document("README.md")


def test_readme_bounds_snap_claim_and_supplies_official_next_steps() -> None:
    readme = document("README.md")
    assert all(word in readme for word in ("district", "county", "state", "snap"))
    assert "below" in readme and "poverty" in readme and "reported" in readme
    assert "undercount" in readme
    assert re.search(r"not (?:an? )?(?:eligibility|enrollment) gap", readme)
    assert "may help" in readme and "agency decides eligibility" in readme
    assert "https://humanservices.hawaii.gov/bessd/snap/" in readme
    assert "211" in readme and "https://www.auw211.org/" in readme


def test_readme_addresses_feature_status_and_update_owners() -> None:
    # Require status coverage, not permanent absence: implementation issues may update it.
    readme = document("README.md")
    assert all(topic in readme for topic in ("chat", "map", "folders", "#183", "#155"))


@pytest.mark.parametrize(
    "topic",
    [
        "prebuilt",
        "read-only",
        "sqlite",
        "data/facts.db",
        "data/snap/facts.db",
        "reference files",
        "no accounts",
        "user content",
        "individual",
        "external links",
        "offline",
        "model",
        "access log",
        "query strings",
        "retention",
        "#183",
        "#155",
        "../etl/census.py",
        "../app/main.py",
        "../app/facts.py",
        "../app/agent/__init__.py",
        "../.gitignore",
        "../makefile",
    ],
)
def test_privacy_covers_runtime_storage_requests_and_evidence(topic: str) -> None:
    assert topic in document("docs/security-privacy.md")
