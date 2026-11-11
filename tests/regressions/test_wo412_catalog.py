"""#414: House 22 offers a fourth match, disability → GA; replaces seven #406/#407 tests."""

from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.copy import section_copy
from app.folders import store
from app.folders.demo import plan
from app.folders.references import decode_match
from app.main import app
from app.tools.matches import DistrictMatches
from etl.programs import load_catalog
from etl.programs.mappings import load_mappings
from tests.regressions import test_journey_folder_save as journey
from tests.regressions import test_wo154_card_suggestions as old
from tests.regressions.test_journey_folder_save import client, flag, live_folders
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo154_missing_matches import missing

__all__ = ["base_url", "browser", "client", "config", "flag", "live_folders", "page"]
__all__ += ["shipped_facts"]

FORM, create, card_id = journey.FORM, journey.create, journey.card_id
folder_store, ABLE, PRE_K, SNAP = journey.folder_store, old.ABLE, old.PRE_K, old.SNAP
WORDS, key, decision, folder_id = old.WORDS, old.key, old.decision, old.folder_id
offered, proposal, suggestions = old.offered, old.proposal, old.suggestions
GA, GA_CHECKED, UNKNOWN = ("disability", "ga"), "2026-11-11", "not-a-program"
CATALOG, DHS_GA = old.ROOT / "data/programs.yaml", "https://humanservices.hawaii.gov/bessd/ga/"
DOSSIER = (old.ROOT / "docs/research/benefit-program-access.md").read_text(encoding="utf-8")
ALL_FOUR = {key(ABLE), key(PRE_K), key(SNAP), key(GA)}
UNOBSERVED = ("age", "household", "income", "assets", "medical", "other benefits")
REFUSALS = old.REFUSALS | {  # GA is supported now: refuse a program the catalog lacks
    "unknown program": (decision(ABLE, program_id=UNKNOWN), "Valid suggestions: disability")
}


def hrefs(node: Node) -> list[str]:
    return [a.attrs["href"] for a in node.find_all("a")]


def test_house_22_offers_four_matches_and_ga_cites_dated_dhs_evidence() -> None:
    (ga,) = (m for m in DistrictMatches(old.HOUSE_22).get_matches() if m.program.id == "ga")
    assert {(m.population_id, m.program_id) for m in load_mappings()} == {ABLE, PRE_K, SNAP, GA}
    m, record = ga.mapping, ga.program.last_verified.isoformat()
    assert (m.claim, m.review_status, m.modeling_evidence) == ("relevant_need", "pending", None)
    # The mapping's own check date is shown, apart from the older program-record date.
    assert record != GA_CHECKED and all(t in m.relevance for t in (DHS_GA, GA_CHECKED, record))
    assert all(c in " ".join(m.unobserved_conditions).casefold() for c in UNOBSERVED)
    response = TestClient(app).get("/match/house/22/ga/disability?preview=1")
    assert response.status_code == 200 and str(ga.program.official_url) == DHS_GA
    article = unescape(response.text).split('<article class="case"', 1)[1].split("</article>")[0]
    for text in (DHS_GA, GA_CHECKED, old.REFERRAL, "may help", "agency decides eligibility"):
        assert text in article
    assert all(c in article for c in m.unobserved_conditions)
    section = DOSSIER.split('<a id="general-assistance"></a>\n\n### General')[1].split("\n### ")[0]
    for text in (DHS_GA, GA_CHECKED, "211", "agency decides", *UNOBSERVED):
        assert text in section.casefold()


def test_every_demo_card_shows_four_suggestions(client: TestClient, tmp_path: Path) -> None:
    db = folder_store(tmp_path / "folders.db")
    db.refresh_demo(plan())
    cards = db.get_folder(store.DEMO_ID).cards
    assert cards and all(decode_match(c.case_id, c.chamber, c.district) is None for c in cards)
    path = f"/f/{store.DEMO_ID}"
    page = client.get(path).text
    for card in cards:
        holder = parse(page).one("div", id=f"suggestions-{card.id}")
        assert holder.attrs["hx-get"] == f"{path}/cards/{card.id}/suggestions"
        assert holder.attrs["hx-trigger"] == "revealed"
        assert holder.one("a").attrs["href"] == holder.attrs["hx-get"]  # works without JS
        shown = offered(suggestions(client, path, card.id))
        assert set(shown) == ALL_FOUR
        for name, node in shown.items():
            chosen = proposal(tuple(name.split(":")))  # pyright: ignore[reportArgumentType] -- two parts
            assert node.attrs["data-source"] == "district_matches"
            assert node.attrs["data-dated"] == chosen.dated.isoformat()
            assert WORDS["source"].format(dated=chosen.dated) in node.text
            assert "may help" in node.text and "agency decides eligibility" in node.text
            links = hrefs(node)
            assert str(chosen.card.match.official_url) in links and old.REFERRAL in links
            assert any(h.startswith("mailto:?subject=") for h in links)  # a link, never a send
        assert DHS_GA in hrefs(shown[key(GA)])
        # The legacy SNAP card's own program: its documented county contacts, each dated.
        assert "Verified 20" in shown[key(SNAP)].text and old.FALLBACK not in shown[key(SNAP)].text
        for pair in (ABLE, PRE_K, GA):  # no documented contacts: official page and 211
            assert old.FALLBACK in shown[key(pair)].text and "Verified" not in shown[key(pair)].text


def test_a_non_strong_match_card_shows_all_four(client: TestClient, tmp_path: Path) -> None:
    db = folder_store(tmp_path / "folders.db")
    folder = db.create_empty_folder("Office")
    db.save_match(folder, proposal(ABLE).match)  # a House 22 MatchReference
    (card,) = db.get_folder(folder).cards
    shown = offered(suggestions(client, f"/f/{folder}", card.id))
    assert set(shown) == ALL_FOUR
    # The card's own match is in the folder already: it says so and offers no decision.
    assert WORDS["in_folder"] in shown[key(ABLE)].text and not shown[key(ABLE)].find_all("form")
    assert len(shown[key(PRE_K)].find_all("form")) == len(shown[key(GA)].find_all("form")) == 2
    assert WORDS["in_folder"] not in shown[key(GA)].text  # same population, other program


def test_decisions_survive_reopen_leaving_ga(client: TestClient, tmp_path: Path) -> None:
    path, other = create(client), create(client)
    card = card_id(client, path)
    url = f"{path}/cards/{card}/suggestions"
    response = client.post(f"{url}/dismiss", content=decision(ABLE), headers=FORM)
    assert (response.status_code, response.headers["location"]) == (303, f"{path}#card-{card}")
    db = folder_store(tmp_path / "folders.db")
    assert len(db.get_folder(folder_id(path)).cards) == 1  # dismissing saves nothing
    reopened = TestClient(client.app, follow_redirects=False)
    assert set(offered(suggestions(reopened, path, card))) == {key(PRE_K), key(SNAP), key(GA)}
    for _ in range(2):  # accepting the same match twice adds one card
        response = client.post(f"{url}/accept", content=decision(PRE_K), headers=FORM)
        assert response.status_code == 303
    saved = db.get_folder(folder_id(path)).cards
    second = offered(suggestions(reopened, path, saved[1].id))  # does not bring ABLE back
    assert key(ABLE) not in second and key(GA) in second
    assert set(offered(missing(reopened, path))) == {key(GA)}
    assert set(offered(missing(reopened, other))) == {key(ABLE), key(PRE_K), key(GA)}
    assert len(saved) == 2 and decode_match(saved[1].case_id, "house", 22) == proposal(PRE_K).match
    decisions = {(d.decision, d.card_id) for d in db.list_decisions(folder_id(path))}
    assert decisions == {("accepted", saved[1].id), ("dismissed", None)}


@pytest.mark.parametrize("case", REFUSALS)
def test_a_forged_or_malformed_reference_is_refused_and_writes_nothing(
    client: TestClient, tmp_path: Path, case: str
) -> None:
    assert len(REFUSALS) == 14 and UNKNOWN not in {p.id for p in load_catalog(CATALOG)}
    body, message = REFUSALS[case]
    path = create(client)
    card = card_id(client, path)
    db = folder_store(tmp_path / "folders.db")
    before = db.get_folder(folder_id(path))
    response = client.post(f"{path}/cards/{card}/suggestions/accept", content=body, headers=FORM)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert message in detail
    if case == "unknown program":  # and disability · ga is now listed as valid
        assert f"'{UNKNOWN}'" in detail and "disability · ga" in detail
    assert (db.get_folder(folder_id(path)), db.list_decisions(folder_id(path))) == (before, ())


def test_missing_matches_subtract_saved_identities(client: TestClient, tmp_path: Path) -> None:
    path = create(client)  # legacy SNAP is already represented
    db = folder_store(tmp_path / "folders.db")
    db.save_case(folder_id(path), "snap_no_receipt", "house", 22)  # repeated identity
    db.save_match(folder_id(path), proposal(PRE_K).match)
    db.save_case(folder_id(path), "snap_no_receipt", "senate", 3)
    assert f'href="{path}?matches=1"' in client.get(path).text
    house, senate = missing(client, path).find_all("div", class_="missing-district")  # exactly 2
    assert set(offered(house)) == {key(ABLE), key(GA)}
    assert set(offered(senate)) == {key(ABLE), key(PRE_K), key(GA)}
    assert "House" in house.text and "Senate" in senate.text
    for pair in (ABLE, GA):
        shown = offered(house)[key(pair)]
        assert shown.attrs["data-source"] == "district_matches"
        assert shown.attrs["data-dated"] == proposal(pair).dated.isoformat()
        assert proposal(pair).dated.isoformat() in shown.text
        assert str(proposal(pair).card.match.official_url) in hrefs(shown)
    document = parse(client.get(f"{path}?matches=1").text)
    ids = [n.attrs["id"] for n in document.find_all() if "id" in n.attrs]
    assert len(ids) == len(set(ids))


def test_browser_reopens_missing_matches_showing_pending_ga(page: Page, live_folders: str) -> None:
    open_page(page, f"{live_folders}/brief/house/22?preview=1", 1440)
    page.get_by_role("button", name=section_copy("case")["save_label"]).click()
    page.wait_for_url("**/f/*")
    folder = page.url.split("#")[0]
    heading = page.get_by_role("link", name=WORDS["heading"], exact=True)
    heading.click()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.locator("button.copy-link").click()
    page.get_by_text("Link copied").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == folder
    assert page.locator(f'[data-suggestion="{key(SNAP)}"]').count() == 0
    for pair, action, cards in ((PRE_K, "accept", 2), (ABLE, "dismiss", 2)):
        offer = page.locator(f'[data-suggestion="{key(pair)}"]')
        offer.get_by_role("button", name=WORDS[action]).click()
        page.wait_for_url("**#card-*")
        assert page.locator(".folder-card").count() == cards  # dismissing adds no card
        heading.click()
    page.goto(folder)
    heading.click()
    assert page.locator(".folder-suggestion").count() == 1
    pending = page.locator(f'[data-suggestion="{key(GA)}"]')  # still awaiting a decision
    for action in ("accept", "dismiss"):
        assert pending.get_by_role("button", name=WORDS[action]).count() == 1
