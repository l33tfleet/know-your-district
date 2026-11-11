"""#407: folder-wide missing matches subtract saved identities and durable decisions."""

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it

from app.copy import load_copy, section_copy  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
from app.folders import routes as folder_routes
from app.folders.references import decode_match  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
from app.tools.suggest_matches import suggest_matches
from app.tools.suggestions import propose
from etl.boundaries import DistrictId
from tests.regressions.test_journey_folder_save import (
    FORM,
    Flag,
    card_id,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
    client,
    create,
    flag,
    folder_store,
    live_folders,
)
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import base_url, browser, open_page  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
from tests.regressions.test_wo122_browser_checks import page as page
from tests.regressions.test_wo143_integration import config, shipped_facts
from tests.regressions.test_wo154_card_suggestions import (
    ABLE,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
    HOUSE_22,
    PRE_K,
    SNAP,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
    WORDS,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
    decision,
    folder_id,
    key,
    offered,
    proposal,  # noqa: F401  # pyright: ignore[reportUnusedImport] -- only superseded tests used it
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
