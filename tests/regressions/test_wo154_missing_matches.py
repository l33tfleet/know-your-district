"""#407: folder-wide missing matches subtract saved identities and durable decisions."""

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.copy import load_copy, section_copy
from app.folders import routes as folder_routes
from app.folders.references import decode_match
from app.tools.suggest_matches import suggest_matches
from app.tools.suggestions import propose
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
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo154_card_suggestions import (
    ABLE,
    HOUSE_22,
    PRE_K,
    SNAP,
    WORDS,
    decision,
    folder_id,
    key,
    offered,
    proposal,
)

__all__ = [
    "base_url",
    "browser",
    "client",
    "config",
    "flag",
    "live_folders",
    "page",
    "shipped_facts",
]


def missing(client: TestClient, path: str) -> Node:
    response = client.get(f"{path}?matches=1")
    assert response.status_code == 200, response.text
    return parse(response.text).one("section", id="missing-matches")


def test_subtraction_preserves_order_and_full_district_identity() -> None:
    house = propose(HOUSE_22)
    senate = propose(DistrictId(chamber="senate", district=3))
    proposals = tuple(reversed(house + senate))
    saved = [p.match for p in house]
    assert suggest_matches(proposals, saved) == tuple(reversed(senate))


def test_missing_matches_subtract_legacy_and_saved_identities_per_district(
    client: TestClient, tmp_path: Path
) -> None:
    path = create(client)  # legacy SNAP is already represented
    db = folder_store(tmp_path / "folders.db")
    db.save_case(folder_id(path), "snap_no_receipt", "house", 22)  # repeated identity
    db.save_match(folder_id(path), proposal(PRE_K).match)
    db.save_case(folder_id(path), "snap_no_receipt", "senate", 3)
    assert f'href="{path}?matches=1"' in client.get(path).text
    section = missing(client, path)
    groups = section.find_all("div", class_="missing-district")
    assert len(groups) == 2
    house, senate = groups
    assert set(offered(house)) == {key(ABLE)}
    assert set(offered(senate)) == {key(ABLE), key(PRE_K)}
    assert "House" in house.text and "Senate" in senate.text
    shown = offered(house)[key(ABLE)]
    assert shown.attrs["data-source"] == "district_matches"
    assert shown.attrs["data-dated"] == proposal(ABLE).dated.isoformat()
    assert proposal(ABLE).dated.isoformat() in shown.text
    assert str(proposal(ABLE).card.match.official_url) in [
        a.attrs["href"] for a in shown.find_all("a")
    ]
    ids = [
        n.attrs["id"]
        for n in parse(client.get(f"{path}?matches=1").text).find_all()
        if "id" in n.attrs
    ]
    assert len(ids) == len(set(ids))


def test_accept_and_dismiss_survive_reopen_without_duplicate_cards(
    client: TestClient, tmp_path: Path
) -> None:
    path, other = create(client), create(client)
    card = card_id(client, path)
    for action, pair in (("accept", PRE_K), ("accept", PRE_K), ("dismiss", ABLE)):
        response = client.post(
            f"{path}/cards/{card}/suggestions/{action}", content=decision(pair), headers=FORM
        )
        assert response.status_code == 303
    reopened = TestClient(client.app, follow_redirects=False)
    assert offered(missing(reopened, path)) == {}
    assert set(offered(missing(reopened, other))) == {key(ABLE), key(PRE_K)}
    db = folder_store(tmp_path / "folders.db")
    saved = db.get_folder(folder_id(path)).cards
    assert len(saved) == 2
    assert decode_match(saved[1].case_id, "house", 22) == proposal(PRE_K).match
    assert {(d.decision, d.card_id) for d in db.list_decisions(folder_id(path))} == {
        ("accepted", saved[1].id),
        ("dismissed", None),
    }


def test_missing_match_accept_is_atomic(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    form = offered(missing(client, path))[key(PRE_K)].find_all("form")[0]
    db = folder_store(tmp_path / "folders.db")
    with sqlite3.connect(db.path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_card BEFORE INSERT ON cards "
            "BEGIN SELECT RAISE(ABORT, 'injected decision failure'); END"
        )
    before = db.get_folder(folder_id(path))
    with pytest.raises(sqlite3.IntegrityError, match="injected decision failure"):
        client.post(form.attrs["action"], content=decision(PRE_K), headers=FORM)
    assert db.get_folder(folder_id(path)) == before
    assert db.list_decisions(folder_id(path)) == ()


def test_missing_view_preserves_source_rejection(client: TestClient, tmp_path: Path) -> None:
    path = create(client)
    form = offered(missing(client, path))[key(PRE_K)].find_all("form")[0]
    response = client.post(
        form.attrs["action"], content=decision(PRE_K, source="chat"), headers=FORM
    )
    assert response.status_code == 422
    assert "Unknown source" in response.text
    db = folder_store(tmp_path / "folders.db")
    assert len(db.get_folder(folder_id(path)).cards) == 1
    assert db.list_decisions(folder_id(path)) == ()


def test_empty_unknown_and_disabled_folders(client: TestClient, tmp_path: Path, flag: Flag) -> None:
    db = folder_store(tmp_path / "folders.db")
    path = f"/f/{db.create_empty_folder('Outreach')}"
    assert offered(missing(client, path)) == {}
    assert client.get(f"/f/{'0' * 32}?matches=1").status_code == 404
    assert flag("off").get(f"{path}?matches=1").status_code == 404


def test_browser_reopens_missing_matches_after_decisions(page: Page, live_folders: str) -> None:
    open_page(page, f"{live_folders}/brief/house/22?preview=1", 1440)
    page.get_by_role("button", name=section_copy("case")["save_label"]).click()
    page.wait_for_url("**/f/*")
    folder = page.url.split("#")[0]
    page.get_by_role("link", name=WORDS["heading"], exact=True).click()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.locator("button.copy-link").click()
    page.get_by_text("Link copied").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == folder
    assert page.locator(f'[data-suggestion="{key(SNAP)}"]').count() == 0
    page.locator(f'[data-suggestion="{key(PRE_K)}"]').get_by_role(
        "button", name=WORDS["accept"]
    ).click()
    page.wait_for_url("**#card-*")
    assert page.locator(".folder-card").count() == 2
    page.get_by_role("link", name=WORDS["heading"], exact=True).click()
    page.locator(f'[data-suggestion="{key(ABLE)}"]').get_by_role(
        "button", name=WORDS["dismiss"]
    ).click()
    page.wait_for_url("**#card-*")
    page.goto(folder)
    page.get_by_role("link", name=WORDS["heading"], exact=True).click()
    assert page.locator(".folder-suggestion").count() == 0


def test_missing_view_uses_shared_copy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    path = create(client)
    words = deepcopy(load_copy())
    words["suggestions"]["heading"] = "Catalog connections marker"
    monkeypatch.setattr(folder_routes, "load_copy", lambda: words)
    document = parse(client.get(path).text)
    link = document.one("a", href=f"{path}?matches=1")
    assert link.text == "Catalog connections marker"
    heading = missing(client, path).one("h2", id="missing-matches-heading")
    assert heading.text == link.text


@pytest.mark.parametrize("value", ["0", "true", "", "1%0A"])
def test_unknown_matches_view_is_refused(client: TestClient, value: str) -> None:
    path = create(client)
    response = client.get(f"{path}?matches={value}")
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["query", "matches"]
    assert error["type"] == "literal_error"
    assert error["ctx"]["expected"] == "'1'"
