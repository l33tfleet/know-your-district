"""#406 (step 2 of #154): grounded, sourced and dated next steps on every saved folder card.

Every card, a legacy case card or a match card of any band (not only strong, which
`load_cards` keeps for the brief), shows the matches the tool offers its district now, each with
its source, date and #150 program card: county contacts with verification dates, or the official
page and 211 when none are documented. Accepting adds the match to the folder as a next step;
dismissing hides it, and the folder remembers that when reopened. Every decision is throttled
and revalidated against the current proposals, so forged or stale references are refused.
"""

import ast
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Locator, Page
from pydantic import ValidationError

from app.copy import load_copy, section_copy
from app.folders import service, store
from app.folders.demo import plan
from app.folders.references import decode_match
from app.program_cards import load_cards, program_cards
from app.tools.matches import DistrictMatches, MatchReference, find_matches  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
from app.tools.suggestions import Proposal, propose
from etl.boundaries import DistrictId
from tests.regressions.test_journey_folder_save import (
    FORM,
    Flag,
    card_id,
    client,
    create,
    flag,
    folder_store,
    live_folders,
)
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import axe_problems, base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts

__all__ = ["base_url", "browser", "client", "config", "flag", "live_folders", "page"]
__all__ += ["shipped_facts"]

ROOT = Path(__file__).resolve().parents[2]
WORDS = load_copy()["suggestions"]
CARD_WORDS = load_copy()["folders"]
HOUSE_22 = DistrictId(chamber="house", district=22)
ABLE = ("disability", "hawaii-able")
PRE_K = ("children_under_5", "public-pre-k")
SNAP = ("below_poverty_no_snap", "snap")
REFERRAL = "https://www.auw211.org/"
FALLBACK = (
    "County contacts not documented. Use official program information or Aloha United Way 211."
)


def proposal(pair: tuple[str, str]) -> Proposal:
    return next(p for p in propose(HOUSE_22) if (p.match.population_id, p.match.program_id) == pair)


def decision(pair: tuple[str, str], **changes: str) -> str:
    chosen = proposal(pair)
    fields = {
        "population_id": pair[0],
        "program_id": pair[1],
        "source": chosen.source,
        "dated": chosen.dated.isoformat(),
    }
    return urlencode({k: v for k, v in (fields | changes).items() if v != "<absent>"})


def suggestions(client: TestClient, path: str, card: int) -> Node:
    response = client.get(f"{path}/cards/{card}/suggestions")
    assert response.status_code == 200, response.text
    return parse(response.text).one("section", class_="folder-suggestions")


def offered(section: Node) -> dict[str, Node]:
    return {
        n.attrs["data-suggestion"]: n for n in section.find_all("div", class_="folder-suggestion")
    }


def key(pair: tuple[str, str]) -> str:
    return ":".join(pair)


def folder_id(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# --- the reusable #150 adapter and the typed proposals ---


def test_the_program_card_adapter_covers_every_band() -> None:
    matches = DistrictMatches(HOUSE_22).get_matches()
    assert {m.result.band for m in matches} == {"insufficient"}  # no strong match in House 22
    assert load_cards(HOUSE_22) == ()  # the brief keeps strong cards only
    cards = program_cards(HOUSE_22, matches)
    assert [c.match.program_id for c in cards] == [m.program.id for m in matches]
    snap = next(c for c in cards if c.match.program_id == "snap")
    assert snap.counties and all(
        contact.verified_on for c in snap.counties for contact in c.contacts
    )
    assert any(c.contacts for c in snap.counties)
    able = next(c for c in cards if c.match.program_id == "hawaii-able")
    assert able.counties and not any(c.contacts for c in able.counties)
    assert all(c.email_url.startswith("mailto:?subject=") for c in cards)


def test_the_adapter_refuses_a_match_from_another_district() -> None:
    other = DistrictMatches(DistrictId(chamber="senate", district=3)).get_matches()
    with pytest.raises(ValueError, match="card's district"):
        program_cards(HOUSE_22, other)


def test_proposals_are_typed_sourced_and_dated_from_the_tool() -> None:
    proposals = propose(HOUSE_22)
    assert [p.match for p in proposals] == list(find_matches(HOUSE_22))
    programs = {m.program.id: m.program for m in DistrictMatches(HOUSE_22).get_matches()}
    for p in proposals:
        assert p.source == "district_matches"
        assert p.dated == programs[p.match.program_id].last_verified
        assert p.card.match.program_id == p.match.program_id


@pytest.mark.parametrize("field", ["source", "dated"])
def test_a_proposal_without_its_source_or_date_is_refused(field: str) -> None:
    raw = proposal(ABLE).model_dump()
    del raw[field]
    with pytest.raises(ValidationError) as refused:
        Proposal.model_validate(raw)
    assert refused.value.error_count() == 1
    assert refused.value.errors()[0]["loc"] == (field,)
    assert refused.value.errors()[0]["type"] == "missing"


def test_a_missing_fact_store_fails_loudly_not_as_no_suggestions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = create(client)
    card = card_id(client, path)
    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "absent.db"))
    with pytest.raises(FileNotFoundError, match="fact store is missing"):
        client.get(f"{path}/cards/{card}/suggestions")


def imports(module: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_tools_cannot_import_folders_and_nothing_sends_email_or_calls_a_model() -> None:
    tool, web = ROOT / "app/tools/suggestions.py", ROOT / "app/web/suggestions.py"
    assert not any(name.startswith("app.folders") for name in imports(tool))
    for module in (tool, web):
        for name in imports(module):
            assert not name.startswith(("app.agent", "smtplib", "email", "anthropic", "httpx")), (
                name
            )
    loaded = subprocess.run(
        [sys.executable, "-c", "import sys, app.tools.suggestions; print(sorted(sys.modules))"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "'app.tools.suggestions'" in loaded
    assert not re.search(r"'(app\.folders|app\.agent|smtplib|anthropic)[.']", loaded)


# --- every card shows them ---


# --- accepting adds a next step; dismissing survives reopening ---


def test_accepting_adds_the_match_as_a_next_step(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    card = card_id(client, path)
    response = client.post(
        f"{path}/cards/{card}/suggestions/accept", content=decision(PRE_K), headers=FORM
    )
    assert response.status_code == 303
    db = folder_store(tmp_path / "folders.db")
    legacy, added = db.get_folder(folder_id(path)).cards
    assert legacy.id == card
    assert decode_match(added.case_id, "house", 22) == proposal(PRE_K).match
    assert (added.status, added.priority) == ("idea", "normal")
    assert response.headers["location"] == f"{path}#card-{added.id}"
    (kept,) = db.list_decisions(folder_id(path))
    assert (kept.decision, kept.card_id, kept.reference.dated) == (
        "accepted",
        added.id,
        proposal(PRE_K).dated,
    )
    page = client.get(path).text
    assert page.count('class="folder-card"') == 2
    shown = offered(suggestions(client, path, card))
    assert WORDS["in_folder"] in shown[key(PRE_K)].text


def test_accepting_on_the_demo_copies_it_and_leaves_the_demo_alone(
    client: TestClient, tmp_path: Path
) -> None:
    db = folder_store(tmp_path / "folders.db")
    db.refresh_demo(plan())
    before = db.get_folder(store.DEMO_ID)
    card = before.cards[0].id
    response = client.post(
        f"/f/{store.DEMO_ID}/cards/{card}/suggestions/accept", content=decision(ABLE), headers=FORM
    )
    assert response.status_code == 303
    copy = response.headers["location"].split("/f/")[1].split("#")[0]
    assert copy != store.DEMO_ID
    assert len(db.get_folder(copy).cards) == len(before.cards) + 1
    assert (db.get_folder(store.DEMO_ID), db.list_decisions(store.DEMO_ID)) == (before, ())


# --- forged, stale and malformed references are refused before any write ---


REFUSALS = {
    "extra field": (decision(ABLE, folder="x"), WORDS["unknown_fields"].split(":")[0]),
    "missing source": (decision(ABLE, source="<absent>"), "Missing form fields: source."),
    "missing dated": (decision(ABLE, dated="<absent>"), "Missing form fields: dated."),
    "leading control": (decision(ABLE, program_id="\thawaii-able"), WORDS["bad_value"]),
    "trailing control": (decision(ABLE, program_id="hawaii-able\n"), WORDS["bad_value"]),
    "embedded control": (decision(ABLE, population_id="disa\x00bility"), WORDS["bad_value"]),
    "line separator": (decision(ABLE, source="district_matches\u2028"), WORDS["bad_value"]),
    "query in id": (decision(ABLE, program_id="hawaii-able?x=1"), WORDS["bad_value"]),
    "encoded id": (decision(ABLE, program_id="hawaii%2dable"), WORDS["bad_value"]),
    "other source": (decision(ABLE, source="chat"), "Unknown source 'chat'"),
    "forged pair": (decision(ABLE, program_id="snap"), "Unknown suggestion 'disability' · 'snap'"),
    "unknown program": (decision(ABLE, program_id="ga"), "Valid suggestions: disability"),
    "forged date": (decision(ABLE, dated="2020-01-01"), "not '2020-01-01'"),
    "malformed date": (decision(ABLE, dated="2026-13-01"), "not '2026-13-01'"),
}


def test_the_district_is_the_saved_cards_own_never_the_forms(
    client: TestClient, tmp_path: Path
) -> None:
    """The form carries no district: a decision on a Senate 3 card is a Senate 3 match."""
    db = folder_store(tmp_path / "folders.db")
    folder = db.create_folder("Office", "snap_no_receipt", "senate", 3)
    (card,) = db.get_folder(folder).cards
    response = client.post(
        f"/f/{folder}/cards/{card.id}/suggestions/accept", content=decision(PRE_K), headers=FORM
    )
    assert response.status_code == 303  # the same pair, offered in Senate 3, is saved there
    added = db.get_folder(folder).cards[1]
    assert (added.chamber, added.district) == ("senate", 3)


def test_another_folders_card_or_an_unknown_action_is_404(
    client: TestClient, tmp_path: Path
) -> None:
    path, other = create(client), create(client)
    card = card_id(client, other)
    for url in (
        f"{path}/cards/{card}/suggestions/accept",
        f"{other}/cards/{card}/suggestions/approve",
    ):
        assert client.post(url, content=decision(ABLE), headers=FORM).status_code == 404
    assert client.get(f"{path}/cards/{card}/suggestions").status_code == 404
    db = folder_store(tmp_path / "folders.db")
    assert db.list_decisions(folder_id(path)) == db.list_decisions(folder_id(other)) == ()


def test_decisions_spend_the_folder_write_limit(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = create(client)
    card = card_id(client, path)
    monkeypatch.setattr(
        service, "WRITE_PER_IP", store.RateRule(scope="write:ip:", limit=1, window_seconds=60)
    )
    url = f"{path}/cards/{card}/suggestions"
    assert client.post(f"{url}/dismiss", content=decision(ABLE), headers=FORM).status_code == 303
    refused = client.post(f"{url}/accept", content=decision(PRE_K), headers=FORM)
    assert refused.status_code == 429 and refused.headers["Retry-After"]
    db = folder_store(tmp_path / "folders.db")
    assert [d.reference.match for d in db.list_decisions(folder_id(path))] == [proposal(ABLE).match]
    assert len(db.get_folder(folder_id(path)).cards) == 1


def test_the_flag_off_hides_every_suggestion_route(client: TestClient, flag: Flag) -> None:
    path = create(client)
    card = card_id(client, path)
    off = flag("off")
    assert off.get(f"{path}/cards/{card}/suggestions").status_code == 404
    post = off.post(f"{path}/cards/{card}/suggestions/accept", content=decision(ABLE), headers=FORM)
    assert post.status_code == 404


# --- in a real browser ---


def reveal(page: Page, number: int) -> Locator:
    """Scroll a card's suggestions into view, as a reader would; htmx then loads them."""
    card = page.locator(".folder-card").nth(number)
    card.locator(".folder-suggestions").scroll_into_view_if_needed()
    loaded = card.locator("section.folder-suggestions")
    loaded.wait_for()
    return loaded


def test_browser_accept_adds_a_next_step_and_dismissal_survives_reopening(
    page: Page, live_folders: str
) -> None:
    open_page(page, f"{live_folders}/brief/house/22?preview=1", 1440)
    page.get_by_role("button", name=section_copy("case")["save_label"]).click()
    page.wait_for_url("**/f/*")
    folder = page.url.split("#")[0]
    assert page.locator(".folder-card").count() == 1
    pre_k = reveal(page, 0).locator(f'[data-suggestion="{key(PRE_K)}"]')
    assert date.fromisoformat(pre_k.get_attribute("data-dated") or "") == proposal(PRE_K).dated
    pre_k.get_by_role("button", name=WORDS["accept"]).click()
    page.locator(".folder-card").nth(1).wait_for()
    assert page.locator(".folder-card").count() == 2
    able = reveal(page, 0).locator(f'[data-suggestion="{key(ABLE)}"]')
    able.get_by_role("button", name=WORDS["dismiss"]).click()
    page.wait_for_load_state("networkidle")
    page.goto(folder)  # reopen the folder's link
    reveal(page, 0)
    reveal(page, 1)
    assert page.get_by_text(CARD_WORDS["suggestions_link"]).count() == 0  # htmx loaded both
    assert page.locator(f'[data-suggestion="{key(SNAP)}"]').count() == 2
    assert page.locator(f'[data-suggestion="{key(ABLE)}"]').count() == 0
    assert axe_problems(page) == []
