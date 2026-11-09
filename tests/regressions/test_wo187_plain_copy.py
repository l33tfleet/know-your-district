"""WO187: the page rule's placeholders and labels, and the rewritten case and program prose.

Replaces test_wo150_prek.py::test_legacy_serialization_and_one_extended_pilot (its
whole-record hashes froze the old guidance) and test_wo100_reliability_rule.py::
test_decimal_constants_and_documented_words (it froze the bare "not available").
"""

import hashlib
import html
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.analysis.reliability import FLAG_WORDS, MODERATE_MAX, RELIABLE_MAX, Z90
from app.cases import load_cases
from app.copy import section_copy
from app.facts import FactStore
from app.main import app
from etl.programs import Program, load_catalog
from scripts.readability import score
from scripts.readability_corpus import (
    AGENCY_STATEMENT,
    PLACEHOLDER,
    check_reading,
    placeholder_names,
    rendered_blocks,
)

ROOT = Path(__file__).resolve().parents[2]
HARD_TAIL = "notwithstanding institutional considerations regarding administrative documentation"


@pytest.fixture(scope="module")
def brief() -> str:
    with TestClient(app) as client:
        response = client.get("/brief/house/1")
    assert response.status_code == 200
    return response.text


# --- The placeholder rule ---------------------------------------------------------


def test_placeholders_come_only_from_the_repo_data_and_the_one_statement() -> None:
    programs = yaml.safe_load((ROOT / "data/programs.yaml").read_text(encoding="utf-8"))
    copy = yaml.safe_load((ROOT / "app/copy.yaml").read_text(encoding="utf-8"))
    islands = json.loads((ROOT / "data/geo/islands/islands.json").read_text(encoding="utf-8"))
    expected = (
        {p[k] for p in programs for k in ("name", "agency")}
        | set(copy["counties"].values())
        | {i["name"] for i in islands["islands"]}
        | {"Aloha United Way", "The agency decides eligibility."}
    )
    names = placeholder_names()
    assert set(names) == expected
    assert len(names) == len(expected)
    # Longest first, so "Hawaiʻi County" is replaced before any shorter name inside it.
    assert [len(n) for n in names] == sorted((len(n) for n in names), reverse=True)
    assert AGENCY_STATEMENT == "The agency decides eligibility."
    assert {"Honolulu County", "Hawaiʻi Island", "Maui", "General Assistance (GA)"} <= set(names)


def test_exact_names_and_the_statement_become_one_short_word() -> None:
    text = (
        "The agency decides eligibility. Call Aloha United Way 211. "
        "Hawaiʻi Department of Human Services, Benefit, Employment & Support Services "
        "Division runs General Assistance (GA) in Honolulu County."
    )
    reading = check_reading(text)
    assert reading.text == f"{PLACEHOLDER} Call {PLACEHOLDER} 211. {PLACEHOLDER} runs " + (
        f"{PLACEHOLDER} in {PLACEHOLDER}."
    )
    assert reading.ok


@pytest.mark.parametrize(
    "near_miss",
    [
        "The agency may decide eligibility.",
        "the agency decides eligibility.",
        "The agency decides eligibility for you.",
        "Aloha United Wey",
        "Supplemental Nutrition Assistance Program",
        "Honolulu Counties",
    ],
)
def test_a_near_miss_is_scored_in_full(near_miss: str) -> None:
    reading = check_reading(near_miss)
    assert PLACEHOLDER not in reading.text.split()
    assert reading.grade == score(near_miss).grade


def test_a_near_miss_statement_fails_where_the_exact_one_passes() -> None:
    assert check_reading("The agency decides eligibility.").ok
    near = check_reading("The agency may decide eligibility.")
    assert near.grade == score("The agency may decide eligibility.").grade
    assert not near.ok


def test_a_long_sentence_with_a_name_still_fails_on_its_other_words() -> None:
    text = f"Supplemental Nutrition Assistance Program (SNAP) {HARD_TAIL}."
    reading = check_reading(text)
    assert reading.text.startswith(PLACEHOLDER)
    assert not reading.label
    assert reading.grade is not None and reading.grade > 8
    assert not reading.ok


# --- The label rule ---------------------------------------------------------------


@pytest.mark.parametrize("label", ["Answer", "Priority", "Hawaiʻi HHS poverty guidelines"])
def test_short_labels_with_short_words_pass(label: str) -> None:
    reading = check_reading(label)
    assert reading.label and reading.ok


@pytest.mark.parametrize("label", ["Check eligibility", "Total population", "not available"])
def test_a_short_label_with_a_long_word_fails(label: str) -> None:
    reading = check_reading(label)
    assert reading.label and not reading.ok and reading.long_words


def test_four_words_or_sentence_punctuation_are_grade_scored() -> None:
    four = check_reading("Households report retirement income")
    assert not four.label and four.grade is not None and not four.ok
    stop = check_reading("Answer.")
    assert not stop.label and stop.grade == score("Answer.").grade
    assert check_reading("This figure is not available").ok


# --- Reliability words (replaces test_decimal_constants_and_documented_words) -------


def test_reliability_constants_and_synchronised_words() -> None:
    assert Decimal("1.645") == Z90
    assert Decimal("0.15") == RELIABLE_MAX
    assert Decimal("0.30") == MODERATE_MAX
    assert all(isinstance(value, Decimal) for value in (Z90, RELIABLE_MAX, MODERATE_MAX))
    assert FLAG_WORDS == {
        "reliable": "reliable",
        "moderate": "moderate: use with care",
        "caution": "use with caution",
        "unavailable": "This figure is not available",
    }
    figures = section_copy("figures")
    profiles = section_copy("profiles")
    assert figures["reliability"] == FLAG_WORDS
    assert profiles["reliability"] == FLAG_WORDS
    assert figures["not_available"] == FLAG_WORDS["unavailable"]
    documentation = (ROOT / "docs/data.md").read_text(encoding="utf-8")
    for words in FLAG_WORDS.values():
        assert words in documentation
        assert check_reading(words).ok, words


# --- The opening case's prose -----------------------------------------------------

CLAIM = (
    "A place to start: survey-reported receipt over the past 12 months is an outreach "
    "signal. This is not current enrollment."
)
UNKNOWN = (
    "Hawaiʻi rules cover who counts as a household, which costs can be deducted, and "
    "more than income. The survey does not cover all these rules."
)
OLD_CLAIM = (
    "A place to start: survey-reported receipt over the past 12 months is an outreach "
    "signal, not current enrollment."
)
OLD_UNKNOWN = "Hawaiʻi household, deduction and nonfinancial rules are not in the survey."


def test_case_fields_are_plain_and_keep_their_limits() -> None:
    record = load_cases().cases[0]
    assert record.claim == CLAIM
    assert dict(record.unknown) == {"program": UNKNOWN}
    for phrase in ("survey-reported receipt", "past 12 months", "outreach signal"):
        assert phrase in record.claim
    assert "not current enrollment" in record.claim
    for phrase in ("household", "deducted", "more than income", "survey does not cover"):
        assert phrase in UNKNOWN
    assert check_reading(CLAIM).ok and check_reading(UNKNOWN).ok
    # Restoring either old field fails the rule.
    assert not check_reading(OLD_CLAIM).ok
    assert not check_reading(OLD_UNKNOWN).ok


def test_case_fields_render_and_their_blocks_pass(brief: str) -> None:
    blocks = rendered_blocks(brief, "house-1")
    claim = [b for b in blocks if CLAIM in b.text]
    unknown = [b for b in blocks if UNKNOWN in b.text]
    assert len(claim) == 1 and len(unknown) == 1
    for block in (*claim, *unknown):
        assert check_reading(block.text, block.citation_spans).ok, block.text
    assert unknown[0].text.startswith(section_copy("case")["unknown_label"])


# --- Programs (replaces test_legacy_serialization_and_one_extended_pilot) -----------

GUIDANCE = "The agency decides eligibility. Call Aloha United Way 211 to find help."
OLD_GUIDANCE = (
    "The agency decides eligibility; contact Aloha United Way 211 for help finding services."
)
GA_PURPOSE = "GA may help adults who cannot work for a while pay for basic needs."
OLD_GA_PURPOSE = "General Assistance may help temporarily disabled adults pay for basic needs."
# The digests WO150 pinned for the whole SNAP and GA records before #187.
OLD_DIGESTS = {
    "snap": "04075a43b898878c8222428be3257c755dd7c835048ef45c57f0991231f64e91",
    "ga": "426cad0a88be43a88f31406f751f201ed8054d44801c15045d0eab5475541e7c",
}
DHS = "Hawaiʻi Department of Human Services, Benefit, Employment & Support Services Division"
SNAP: dict[str, object] = {
    "agency": DHS,
    "agency_guideline": {
        "description": (
            "DHS SNAP gross monthly income chart, BBCE column; other agency rules also apply."
        ),
        "effective_date": "2026-10-01",
        "poverty_line": "Hawaiʻi HHS poverty guidelines",
        "source_url": "https://humanservices.hawaii.gov/bessd/snap/",
        "threshold": 2.0,
    },
    "eligibility_proxy": {
        "acs_fields": [f"C17002_00{n}E" for n in range(2, 8)],
        "geography": "Hawaiʻi legislative districts, 2022 plan",
        "method": (
            "Population below 2.00 times the national Census poverty threshold, derived by "
            "summing complete C17002 brackets without interpolation; sum margins of error in "
            "quadrature. This is a lower bound: national thresholds understate the population "
            "below the higher Hawaiʻi HHS guidelines. This population proxy does not "
            "determine program eligibility or count households."
        ),
        "poverty_line": "national Census poverty thresholds",
        "source_url": "https://api.census.gov/data/2024/acs/acs5/groups/C17002.json",
        "status": "available",
        "threshold": 2.0,
        "vintage": "2020–2024",
    },
    "guidance": GUIDANCE,
    "id": "snap",
    "last_verified": "2026-10-25",
    "level": "federal",
    "name": "Supplemental Nutrition Assistance Program (SNAP)",
    "official_url": "https://humanservices.hawaii.gov/bessd/snap/",
    "purpose": "SNAP may help households pay for food.",
    "referral_url": "https://www.auw211.org/",
    "retired": None,
}
GA: dict[str, object] = {
    "agency": DHS,
    "agency_guideline": {
        "description": (
            "DHS requires medical-board certification and income, asset and household conditions."
        ),
        "effective_date": None,
        "poverty_line": "not applicable",
        "source_url": "https://humanservices.hawaii.gov/bessd/ga/",
        "threshold": None,
    },
    "eligibility_proxy": {
        "acs_fields": [],
        "geography": "Hawaiʻi legislative districts, 2022 plan",
        "method": (
            "No ACS proxy is available: published district tables cannot identify DHS "
            "medical-board certification, temporary inability to work, asset limits and "
            "exclusion from other assistance categories together."
        ),
        "poverty_line": None,
        "source_url": "https://humanservices.hawaii.gov/bessd/ga/",
        "status": "unavailable",
        "threshold": None,
        "vintage": None,
    },
    "guidance": GUIDANCE,
    "id": "ga",
    "last_verified": "2026-10-25",
    "level": "state",
    "name": "General Assistance (GA)",
    "official_url": "https://humanservices.hawaii.gov/bessd/ga/",
    "purpose": GA_PURPOSE,
    "referral_url": "https://www.auw211.org/",
    "retired": None,
}


def test_legacy_serialization_keeps_every_fact_and_one_extended_pilot() -> None:
    programs = load_catalog(ROOT / "data/programs.yaml")
    raw = yaml.safe_load((ROOT / "data/programs.yaml").read_text())
    assert len(programs) == 4
    for expected in (SNAP, GA):
        program = next(p for p in programs if p.id == expected["id"])
        original = next(p for p in raw if p["id"] == expected["id"])
        assert set(program.model_dump()) == set(original) | {"retired"}
        assert set(json.loads(program.model_dump_json())) == set(original) | {"retired"}
        assert not {"rules", "next_steps", "enrichment"} & program.model_dump().keys()
        dumped = program.model_dump(mode="json")
        assert dumped == expected
        # Only the rewritten prose differs from the record WO150 hashed: putting the
        # old words back reproduces its digest exactly, so every fact is unchanged.
        dumped["guidance"] = OLD_GUIDANCE
        if expected["id"] == "ga":
            dumped["purpose"] = OLD_GA_PURPOSE
        serialized = json.dumps(dumped, sort_keys=True)
        assert hashlib.sha256(serialized.encode()).hexdigest() == OLD_DIGESTS[program.id]
    pilot = next(p for p in programs if p.id == "hawaii-able")
    assert pilot.rules and pilot.next_steps and pilot.enrichment and programs[-1] == pilot
    assert Program.model_validate_json(pilot.model_dump_json()) == pilot
    for ref in pilot.enrichment.fact_references:
        assert FactStore.default().get([(ref.variable, ref.geography)], ref.vintage)


def test_every_program_keeps_the_statement_211_and_its_links() -> None:
    for program in load_catalog(ROOT / "data/programs.yaml"):
        assert program.guidance == GUIDANCE
        assert program.guidance.startswith("The agency decides eligibility.")
        assert "Aloha United Way 211" in program.guidance
        assert str(program.referral_url) == "https://www.auw211.org/"
        assert str(program.official_url).startswith("https://")
        assert check_reading(program.purpose).ok, program.purpose
    assert not check_reading(OLD_GUIDANCE).ok
    assert not check_reading(OLD_GA_PURPOSE).ok


def test_rendered_program_guidance_passes_and_keeps_its_referrals(brief: str) -> None:
    blocks = rendered_blocks(brief, "house-1")
    guidance = [b for b in blocks if b.text.startswith(GUIDANCE)]
    assert len(guidance) == len(load_catalog(ROOT / "data/programs.yaml"))
    for block in guidance:
        assert block.text == f"{GUIDANCE} Aloha United Way 211"
        assert check_reading(block.text).ok
    assert brief.count('href="https://www.auw211.org/"') >= len(guidance)
    for program in load_catalog(ROOT / "data/programs.yaml"):
        assert f'href="{program.official_url}"' in brief
        assert program.name in html.unescape(brief)
        assert program.agency in html.unescape(brief)
