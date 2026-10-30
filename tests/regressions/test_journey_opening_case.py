"""#286 (journey step 1): the brief opens with the SNAP outreach case, above the figures.

A case is a validated record in `data/cases.yaml`. The card reads the same SNAP result as
section 40 and shows the same value, margin of error and reliability word, with its own
citation and the undercount note. It says who may benefit, why this district and the next
step, and never says "eligible", "qualify" or "not enrolled".
"""

import copy
import importlib
import re
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from playwright.sync_api import Page
from pydantic import ValidationError

import app.copy
from app import cases, features, populations, snap
from app.main import app as asgi_app
from app.page_state import page_state
from etl.boundaries import DISTRICT_COUNTS, Chamber, DistrictId
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, live_config, pdf_pages, shipped_facts

# Reuse the WO122 server and Chromium fixtures and the WO196 print fixtures unchanged.
__all__ = ["base_url", "browser", "config", "live_config", "page", "shipped_facts"]

ROOT = Path(__file__).resolve().parents[2]
COPY: dict[str, Any] = yaml.safe_load(app.copy.COPY_PATH.read_text(encoding="utf-8"))
CASE_COPY: dict[str, Any] = COPY["sections"]["case"]
SHIPPED: dict[str, Any] = yaml.safe_load((ROOT / "data/cases.yaml").read_text(encoding="utf-8"))
BANNED = ("eligible", "qualify", "not enrolled")
HOUSE_22 = "house:15:022:2022"

Configure = Callable[[str], TestClient]


@pytest.fixture
def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Configure:
    def write_config(text: str) -> TestClient:
        path = tmp_path / "features.toml"
        path.write_text(text)
        monkeypatch.setattr(features, "FEATURES_PATH", path)
        return TestClient(asgi_app)

    return write_config


def flat(node: Node) -> str:
    # Word-break elements split parser chunks without adding visible spaces.
    return " ".join("".join(node.parts).split())


def card(client: TestClient, path: str = "/brief/house/22") -> Node:
    response = client.get(path)
    assert response.status_code == 200
    return parse(response.text).one("section", class_="case")


def section_40(client: TestClient, path: str = "/brief/house/22") -> Node:
    return parse(client.get(path).text).one("section", class_="outreach")


def hrefs(node: Node) -> list[str | None]:
    return [a.attrs.get("href") for a in node.find_all("a")]


# --- the card, on every district ---


@pytest.mark.parametrize("chamber", list(DISTRICT_COUNTS))
def test_every_district_shows_section_40_reading_above_the_figures(chamber: Chamber) -> None:
    client = TestClient(asgi_app)
    for number in range(1, DISTRICT_COUNTS[chamber] + 1):
        path = f"/brief/{chamber}/{number}"
        html = client.get(path).text
        assert html.index("<h1") < html.index('class="case"') < html.index('class="figure"')
        document = parse(html)
        found = document.one("section", class_="case")
        evidence = document.one("section", class_="outreach").one("tbody").find_all("tr")[0]
        assert flat(found.one("p", class_="case-reading")) == flat(evidence.one("td").one("p"))
        lowered = found.text.casefold()
        assert not [word for word in BANNED if word in lowered], path


def test_card_says_who_why_and_what_next() -> None:
    found = card(TestClient(asgi_app), "/brief/senate/5")
    record = cases.case("snap_no_receipt")
    result = snap.load_result(DistrictId(chamber="senate", district=5))
    assert found.one("h2").text == "Households in poverty reporting no SNAP receipt · SNAP"
    text = flat(found)
    assert record.claim in text
    assert "survey-reported receipt over the past 12 months" in record.claim
    assert "an outreach signal" in record.claim
    assert "not current enrollment" in record.claim
    for words in (*record.known.values(), *record.unknown.values()):
        assert words in text
    assert CASE_COPY["known_label"] in text and CASE_COPY["unknown_label"] in text
    assert CASE_COPY["gaps"][record.failure.gap] in text
    assert record.failure.note in text
    assert CASE_COPY["actions"][record.action.kind] in text
    assert result.referral_note in text
    assert "may help" in text and "DHS decides eligibility" in text
    assert record.program.rule_checked.isoformat() in text


def test_card_cites_the_figure_and_notes_the_undercount_beside_it() -> None:
    """R1 and the benefit undercount trap apply to the card itself, not only to section 40."""
    found = card(TestClient(asgi_app), "/brief/senate/5")
    result = snap.load_result(DistrictId(chamber="senate", district=5))
    fact = result.district.fact
    assert fact is not None
    citation = flat(found.one("p", class_="case-citation"))
    for field in (fact.source, fact.table_id, fact.vintage, fact.geography, fact.method):
        assert field in citation
    assert result.undercount_note in flat(found.one("div", class_="case-figure"))


def test_next_step_links_and_the_evidence_jump() -> None:
    client = TestClient(asgi_app)
    found = card(client)
    result = snap.load_result(DistrictId(chamber="house", district=22))
    assert result.referral is not None
    links = hrefs(found.one("p", class_="case-next"))
    assert links == [result.official_url, str(result.referral.outreach_url), result.referral_url]
    evidence = next(a for a in found.find_all("a") if a.text == CASE_COPY["evidence_link"])
    assert CASE_COPY["evidence_link"] == "County and state figures, and the source"
    target = evidence.attrs["href"]
    assert target == "#outreach-heading"
    assert section_40(client).one("h2").attrs["id"] == target.removeprefix("#")


def test_record_links_cannot_drift_from_the_section_40_links() -> None:
    record = cases.case("snap_no_receipt")
    snap_copy = COPY["sections"]["snap"]
    assert str(record.program.url) == snap_copy["official_url"]
    assert snap_copy["referral_url"] in [str(link.url) for link in record.action.links]


def test_every_gap_and_action_has_card_words_without_a_banned_word() -> None:
    assert set(CASE_COPY["gaps"]) == set(get_args(cases.Gap))
    assert set(CASE_COPY["actions"]) == set(get_args(cases.ActionKind))
    for words in (*CASE_COPY["gaps"].values(), *CASE_COPY["actions"].values()):
        assert not [banned for banned in BANNED if banned in words.casefold()]


def test_research_anchor_is_a_heading_of_the_dossier() -> None:
    document, _, anchor = cases.case("snap_no_receipt").research.partition("#")
    lines = (ROOT / document).read_text(encoding="utf-8").splitlines()
    assert anchor in ["-".join(h.lstrip("# ").lower().split()) for h in lines if h[:1] == "#"]


# --- unavailable reading ---


@pytest.mark.parametrize("missing", ["database", "row", "estimate"])
def test_no_reading_says_so_and_keeps_the_next_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    database = tmp_path / "facts.db"
    if missing != "database":
        shutil.copyfile(snap.SNAP_DB, database)
        with sqlite3.connect(database) as db:
            if missing == "row":
                db.execute("DELETE FROM facts WHERE geography = ?", [HOUSE_22])
            else:
                db.execute(
                    "UPDATE facts SET value = NULL, cv = NULL, reliability = 'unavailable' "
                    "WHERE geography = ?",
                    [HOUSE_22],
                )
    monkeypatch.setattr(snap, "SNAP_DB", database)
    found = card(TestClient(asgi_app))
    assert CASE_COPY["unavailable"].format(district="Hawaiʻi State House District 22") in flat(
        found
    )
    assert not found.find_all("p", class_="case-reading")
    assert not found.find_all("p", class_="case-citation")
    assert cases.case("snap_no_receipt").claim not in flat(found)
    links = hrefs(found.one("p", class_="case-next"))
    assert "https://humanservices.hawaii.gov/bessd/snap/" in links
    assert "https://auw211.org/" in links


def test_missing_margin_of_error_is_not_an_unavailable_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "facts.db"
    shutil.copyfile(snap.SNAP_DB, database)
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE facts SET moe = NULL, cv = NULL, reliability = 'caution' WHERE geography = ?",
            [HOUSE_22],
        )
    monkeypatch.setattr(snap, "SNAP_DB", database)
    reading = flat(card(TestClient(asgi_app)).one("p", class_="case-reading"))
    assert "no margin of error published" in reading
    assert "use with caution" in reading


def test_missing_referrals_file_drops_only_the_dhs_outreach_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snap, "REFERRALS_PATH", tmp_path / "absent.json")
    found = card(TestClient(asgi_app))
    assert hrefs(found.one("p", class_="case-next")) == [
        "https://humanservices.hawaii.gov/bessd/snap/",
        "https://auw211.org/",
    ]
    assert found.find_all("p", class_="case-reading")


# --- the flag, and how often the result loads ---


def test_outreach_off_hides_the_card(configure: Configure) -> None:
    html = configure('outreach = "off"\n').get("/brief/house/22").text
    assert not parse(html).find_all("section", class_="case")
    assert "SNAP receipt" not in html and "B22003" not in html


def test_off_hides_form_and_route_and_loads_the_result_once_per_section(
    configure: Configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaces test_wo136_answer.py::test_off_hides_form_and_route_and_skips_result_load."""
    calls: list[DistrictId] = []
    original = snap.load_result

    def counted(district: DistrictId) -> snap.SnapResult:
        calls.append(district)
        return original(district)

    monkeypatch.setattr(snap, "load_result", counted)
    client = configure('outreach = "on"\nsnap_question = "off"\n')
    for query in ("", "&preview=1"):
        calls.clear()
        shown = client.get(f"/brief/house/22?v=a{query}")
        assert shown.status_code == 200
        assert not parse(shown.text).find_all("section", class_="snap-question")
        # The opening case and section 40 show it; each loads it exactly once.
        assert len(calls) == 2
        calls.clear()
        route = client.get(f"/brief/house/22/snap-answer?question=no_snap_households{query}")
        assert route.status_code == 404
        assert "text/html" in route.headers["content-type"]
        # Hidden even when the question itself is unknown: off never reveals the route.
        assert client.get("/brief/house/22/snap-answer?question=other").status_code == 404
        assert calls == []
    client = configure('outreach = "off"\nsnap_question = "off"\n')
    for query in ("", "&preview=1"):
        assert client.get(f"/brief/house/22?v=a{query}").status_code == 200
        path = f"/brief/house/22/snap-answer?question=no_snap_households{query}"
        assert client.get(path).status_code == 404
    assert calls == []


def test_save_slot_renders_only_when_a_later_step_passes_a_control() -> None:
    assert "case-save" not in TestClient(asgi_app).get("/brief/house/22").text
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"])
    )
    template = env.get_template("sections/15-case.html")
    module = importlib.import_module("app.sections.15_case")
    state = page_state("house", "22")
    section: dict[str, object] = module.context(state)
    plain = template.render(section=section, copy=CASE_COPY, state=state)
    assert "case-save" not in plain
    slot = Markup("<button>Save to folder</button>")
    saved = template.render(section=section | {"save_control": slot}, copy=CASE_COPY, state=state)
    assert parse(saved).one("div", class_="case-save").one("button").text == "Save to folder"


# --- screen and print ---


@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
@pytest.mark.parametrize("width", [390, 1440])
def test_screen_and_print_show_the_same_card(
    page: Page, shipped_facts: str, live_config: Path, variant: str, width: int
) -> None:
    open_page(page, shipped_facts + "/brief/senate/5" + variant, width)
    assert axe_problems(page) == []
    found = page.locator("section.case")
    assert found.is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screen = found.inner_text()
    page.emulate_media(media="print")
    assert found.is_visible()
    assert found.inner_text() == screen
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("path", ["/brief/house/22", "/brief/senate/5"])
@pytest.mark.parametrize("variant", ["", "?v=a", "?v=b"])
def test_print_keeps_room_to_spare_on_one_page(
    page: Page, shipped_facts: str, live_config: Path, path: str, variant: str
) -> None:
    """Variant B's system-ui differs per machine, so a tight local fit proves nothing:
    widened text stands in for a wider font, with no font name in the test."""
    open_page(page, shipped_facts + path + variant, 1440)
    page.add_style_tag(content=".brief, .site-footer { letter-spacing: 0.04em; }")
    assert pdf_pages(page) == 1


def test_print_rules_for_the_outreach_notes_are_valid_selectors() -> None:
    """A relative selector inside :is() is dropped silently, which printed the notes full size."""
    assert not re.search(r":is\(\s*>", (ROOT / "static/site.css").read_text())


# --- the record ---


def write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    return path


def record() -> dict[str, Any]:
    document = copy.deepcopy(SHIPPED)
    assert len(document["cases"]) == 1
    only: dict[str, Any] = document["cases"][0]
    return only


def load(tmp_path: Path, *records: dict[str, Any]) -> cases.CaseFile:
    return cases.load_cases(write(tmp_path, {"cases": list(records)}))


def failures(error: ValidationError) -> list[tuple[object, str]]:
    # A bad item inside a sized tuple also reports the tuple as too short.
    return [(e["loc"][-1], e["type"]) for e in error.errors()]


def test_shipped_record_is_the_snap_case_the_work_order_describes() -> None:
    shipped = cases.load_cases().cases
    assert [c.id for c in shipped] == ["snap_no_receipt"]
    only = shipped[0]
    assert only.population == "below_poverty_no_snap"
    assert only.population in [p.id for p in populations.load_populations().populations]
    assert only.failure.gap == "eligible_nonparticipation"
    assert only.failure.note == "not measured: survey receipt is an outreach signal"
    assert set(only.known) == {"geography", "population"}
    assert set(only.unknown) == {"program"}
    assert "B22003_006" in only.known["population"]
    assert "Hawaiʻi" in only.unknown["program"]
    assert only.action.kind == "navigator_referral"
    assert only.research == "docs/research/benefit-program-access.md#snap-and-cofa"


def test_shipped_record_passes_the_loader_the_negative_tests_use(tmp_path: Path) -> None:
    assert [c.id for c in load(tmp_path, record()).cases] == ["snap_no_receipt"]


def test_load_reads_the_path_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    changed = record() | {"id": "moved"}
    monkeypatch.setattr(cases, "CASES_PATH", write(tmp_path, {"cases": [changed]}))
    assert [c.id for c in cases.load_cases().cases] == ["moved"]


def test_rejects_an_unknown_population_id(tmp_path: Path) -> None:
    bad = record() | {"population": "no_such_population"}
    with pytest.raises(ValueError, match=r"snap_no_receipt: unknown population no_such_population"):
        load(tmp_path, bad)


def test_rejects_an_unknown_gap_type(tmp_path: Path) -> None:
    bad = record()
    bad["failure"]["gap"] = "unclaimed_dollars"
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert ("gap", "literal_error") in failures(error.value)
    assert "eligible_nonparticipation" in str(error.value)


def test_rejects_an_unknown_action(tmp_path: Path) -> None:
    bad = record()
    bad["action"]["kind"] = "press_release"
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert ("kind", "literal_error") in failures(error.value)
    assert "navigator_referral" in str(error.value)


def test_rejects_a_record_without_unknown(tmp_path: Path) -> None:
    bad = record()
    del bad["unknown"]
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert ("unknown", "missing") in failures(error.value)


def test_rejects_an_empty_unknown(tmp_path: Path) -> None:
    bad = record()
    bad["known"]["program"] = bad["unknown"].pop("program")
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert ("unknown", "too_short") in failures(error.value)


def test_rejects_a_problem_listed_nowhere(tmp_path: Path) -> None:
    bad = record()
    del bad["known"]["geography"]
    with pytest.raises(ValidationError, match="snap_no_receipt: neither known nor unknown: geo"):
        load(tmp_path, bad)


def test_rejects_a_problem_listed_as_both_known_and_unknown(tmp_path: Path) -> None:
    bad = record()
    bad["known"]["program"] = "Listed twice."
    with pytest.raises(ValidationError, match="snap_no_receipt: both known and unknown: program"):
        load(tmp_path, bad)


def test_rejects_an_unknown_evidence_problem(tmp_path: Path) -> None:
    bad = record()
    bad["unknown"]["politics"] = "Not one of the three."
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert "literal_error" in [kind for _, kind in failures(error.value)]


@pytest.mark.parametrize(
    "where", [(), ("program",), ("failure",), ("action",), ("action", "links", 0)]
)
def test_rejects_an_unknown_field(tmp_path: Path, where: tuple[str | int, ...]) -> None:
    bad = record()
    target: Any = bad
    for key in where:
        target = target[key]
    target["surprise"] = "x"
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert ("surprise", "extra_forbidden") in failures(error.value)


def test_rejects_a_duplicate_case_id(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="duplicate case id: snap_no_receipt"):
        load(tmp_path, record(), record())


def test_rejects_an_action_with_no_next_step(tmp_path: Path) -> None:
    bad = record()
    bad["action"]["links"] = []
    with pytest.raises(ValidationError) as error:
        load(tmp_path, bad)
    assert ("links", "too_short") in failures(error.value)


def test_rejects_a_file_with_no_cases(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as error:
        load(tmp_path)
    assert failures(error.value) == [("cases", "too_short")]


def test_case_lookup_rejects_an_unknown_id() -> None:
    with pytest.raises(KeyError, match="no_such_case"):
        cases.case("no_such_case")
