"""WO #3: the written rules exist, carry what the work order requires, and agree."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

LAYOUT = [
    "app",
    "app/sections",
    "app/analysis",
    "app/tools",
    "app/agent",
    "app/web",
    "etl",
    "data",
    "templates",
    "static",
    "scripts",
    "docs",
    "tests/regressions",
    "tests/golden",
    "tests/evals",
]

# One keyword per product rule (Notes of WO #3), checked in AGENTS.md and the rubric.
RULE_KEYWORDS = [
    "table ID",
    "margin of error",
    "language model",
    "individuals",
    "Nonpartisan",
    "ʻokina",
    "211",
]

INDICATORS = [
    "B01003_001E",
    "DP05_0024PE",
    "B19013_001E",
    "S1701_C03_001E",
    "S1701_C03_010E",
    "S2301_C04_001E",
    "B22010_002E",
    "S2201_C04_001E",
    "B19055_002E",
    "B19059_002E",
    "DP04_0142PE",
    "B25064_001E",
    "S2701_C05_001E",
    "S1810_C03_001E",
    "S1602_C04_001E",
    "B08201_002E",
    "C17002_001E",
    "C17002_008E",
]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", LAYOUT)
def test_layout_folder_exists(rel: str) -> None:
    assert (ROOT / rel).is_dir()


@pytest.mark.parametrize(
    "rel",
    [
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "docs/data.md",
        ".factory/review.md",
        ".github/CODEOWNERS",
    ],
)
def test_written_rules_exist(rel: str) -> None:
    assert read(rel).strip()


def test_claude_md_points_to_agents_md() -> None:
    assert "AGENTS.md" in read("CLAUDE.md")


@pytest.mark.parametrize("keyword", RULE_KEYWORDS)
def test_product_rules_in_agents_and_rubric(keyword: str) -> None:
    assert keyword in read("AGENTS.md")
    assert keyword in read(".factory/review.md")


def test_rubric_has_one_checkable_line_per_rule() -> None:
    rubric = read(".factory/review.md")
    numbered = re.findall(r"^\s*-\s*\[ \]\s*\*\*R(\d)\b", rubric, flags=re.MULTILINE)
    assert sorted(set(numbered)) == [str(n) for n in range(1, 8)]


@pytest.mark.parametrize(
    "pin",
    [
        "Python 3.12",
        "uv",
        "uvicorn app.main:app",
        "FastAPI",
        "Jinja2",
        "htmx 2.0",
        "htmx 4",
        "Leaflet 1.9",
        "SVG renderer",
        "SQLite",
        "read-only",
        "Pydantic",
    ],
)
def test_stack_pins_in_agents_md(pin: str) -> None:
    assert pin in read("AGENTS.md")


def test_agents_md_states_test_placement_rule() -> None:
    agents = read("AGENTS.md")
    assert "tests/regressions/" in agents
    assert "append-only" in agents
    assert "Supersedes:" in agents


def test_agents_md_lists_layout() -> None:
    agents = read("AGENTS.md")
    for rel in LAYOUT:
        assert f"`{rel}/`" in agents, rel


def test_data_md_lists_indicators_vintage_and_thresholds() -> None:
    data = read("docs/data.md")
    for variable in INDICATORS:
        assert variable in data, variable
    assert "https://api.census.gov/data/2024/acs/acs5" in data
    assert "2020–2024" in data
    assert "1.645" in data
    assert "15%" in data and "30%" in data
    assert "Kalawao" in data
    assert "81" in data
    for bracket in ("0.50", "1.00", "1.25", "1.50", "1.85", "2.00"):
        assert bracket in data


def test_codeowners_owns_guard_rails_but_not_regressions() -> None:
    lines = [
        line.split()
        for line in read(".github/CODEOWNERS").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    owned = {parts[0]: parts[1:] for parts in lines}
    for pattern in [
        "/fixtures/",
        "/scripts/independent_*",
        "conftest.py",
        "pyproject.toml",
        "/.github/",
        "/Makefile",
        "/AGENTS.md",
        "/CLAUDE.md",
        "/.factory/",
    ]:
        assert owned.get(pattern) == ["@k7lim"], pattern
    assert not any(
        p.startswith("/tests/regressions") or p.startswith("tests/regressions") for p in owned
    )


def test_readme_says_how_to_run_from_clean_clone() -> None:
    readme = read("README.md")
    for needle in (
        "uv sync",
        "make check",
        "make run",
        "make smoke",
        "https://district.hawaiitechmentors.org",
    ):
        assert needle in readme, needle


def test_gitignore_covers_secrets_and_caches() -> None:
    ignored = read(".gitignore")
    for needle in (".env", ".venv", "data/cache/"):
        assert needle in ignored, needle


def test_ci_has_tests_and_append_only_jobs() -> None:
    workflows = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / ".github" / "workflows").glob("*.yml")
    )
    assert re.search(r"^  tests:", workflows, flags=re.MULTILINE)
    assert re.search(r"^  regressions-append-only:", workflows, flags=re.MULTILINE)
    assert "make check" in workflows
    assert "regressions_append_only.py" in workflows
