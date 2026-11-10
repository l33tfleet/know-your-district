"""#412 (step 1 of #155): the demo folder's match seed.

`python -m app.folders.demo --matches` resolves three House 22 matches through the matching tool
and seeds them as match cards with distinct statuses, dated outreach-only notes and accepted
suggestion decisions; proposals beyond the seeded ones stay pending (no decision row). The seed
replaces only the reserved demo id in one transaction, preview writes nothing, and a visitor's
first edit copies the decisions with the cards and notes.
"""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.folders import demo, store
from app.folders.references import decode_match, encode_match
from app.suggestions import SuggestionReference
from app.tools.suggestions import propose
from etl.boundaries import DistrictId
from tests.regressions.test_journey_folder_save import client, flag, folder_store, rows
from tests.regressions.test_wo97_brief_page import parse

__all__ = ["client", "flag"]
HOUSE_22 = DistrictId(chamber="house", district=22)
SEED = f"/f/{store.DEMO_ID}"
HELD = "Already in this folder as a next step."


@pytest.fixture
def seeded(client: TestClient, tmp_path: Path) -> store.FolderStore:
    db = folder_store(tmp_path / "folders.db")
    db.refresh_demo_matches(demo.match_plan())
    return db


def snapshot(db: store.FolderStore, folder_id: str) -> tuple[object, ...]:
    """Everything a folder holds, without the database ids a copy renumbers."""
    folder = db.get_folder(folder_id)
    keys = {card.id: card.case_id for card in folder.cards}
    return (
        folder.name,
        [(c.case_id, c.chamber, c.district, c.priority, c.status) for c in folder.cards],
        [(keys[n.card_id], n.dated, n.body) for n in db.list_notes(folder_id)],
        [
            (d.reference, d.decision, d.card_id is not None and keys[d.card_id])
            for d in db.list_decisions(folder_id)
        ],
    )


def test_match_plan_resolves_three_house_22_matches_with_distinct_state(
    client: TestClient,
) -> None:
    plan = demo.match_plan()
    proposals = {p.match: p for p in propose(HOUSE_22)}
    assert len(plan) == 3
    assert all(seed.match in proposals for seed in plan)
    assert [seed.match for seed in plan] == list(proposals)[:3]  # the tool's ranked order
    for seed in plan:
        assert (seed.source, seed.checked) == (
            proposals[seed.match].source,
            proposals[seed.match].dated,
        )
    assert len({seed.status for seed in plan}) == 3
    assert len({seed.dated for seed in plan}) == 3
    for seed in plan:
        assert "211" in seed.body and "qualif" not in seed.body.lower()
    with pytest.raises(ValidationError):
        store.DemoMatch.model_validate(plan[0].model_dump() | {"body": "Call 808-555-0142"})
    with pytest.raises(ValidationError):
        store.DemoMatch.model_validate(plan[0].model_dump() | {"dated": "soon"})


def test_direct_url_renders_three_sourced_match_cards_and_their_decisions(
    seeded: store.FolderStore, client: TestClient
) -> None:
    response = client.get(SEED)
    assert response.status_code == 200
    document = parse(response.text)
    assert len(document.find_all("div", class_="folder-card")) == 3
    articles = document.find_all("article", class_="case")
    assert len(articles) == 3
    for part in ("case-reading", "case-source"):  # the tool's figure and its dated source
        assert len(document.find_all("p", class_=part)) == 3
    folder = seeded.get_folder(store.DEMO_ID)
    decided = {d.reference.match: d for d in seeded.list_decisions(store.DEMO_ID)}
    plan = demo.match_plan()
    assert list(decided) == [seed.match for seed in plan]
    assert all(d.decision == "accepted" for d in decided.values())
    for seed in plan:
        card = decided[seed.match].card_id
        assert card is not None
        key = next(c.case_id for c in folder.cards if c.id == card)
        assert decode_match(key, "house", 22) == seed.match
    pending = [p for p in propose(HOUSE_22) if p.match not in decided]
    for card in folder.cards:
        panel = client.get(f"{SEED}/cards/{card.id}/suggestions")
        assert panel.status_code == 200
        assert panel.text.count(HELD) == len(decided)
        assert panel.text.count("/suggestions/accept") == len(pending)
    assert [n.dated for n in seeded.list_notes(store.DEMO_ID)] == [s.dated for s in plan]


def test_reset_is_repeatable_keeps_the_url_and_leaves_other_folders(
    seeded: store.FolderStore, client: TestClient
) -> None:
    other = seeded.create_folder("Other office", "snap_no_receipt", "house", 22)
    seeded.decide(
        other,
        SuggestionReference(
            match=(first := propose(HOUSE_22)[0]).match, source=first.source, dated=first.dated
        ),
        "dismissed",
    )
    kept = snapshot(seeded, other)
    kept_rows = rows(seeded.path, f"SELECT * FROM folders WHERE id = '{other}'")
    seed = snapshot(seeded, store.DEMO_ID)
    page = client.get(SEED).text.count('class="folder-card"')
    for _ in range(2):
        seeded.refresh_demo_matches(demo.match_plan())
        assert snapshot(seeded, store.DEMO_ID) == seed
        assert client.get(SEED).text.count('class="folder-card"') == page == 3
        assert snapshot(seeded, other) == kept
        assert rows(seeded.path, f"SELECT * FROM folders WHERE id = '{other}'") == kept_rows
    # The legacy reset still replaces the match seed, and the match seed replaces it again.
    seeded.refresh_demo(demo.plan())
    assert seeded.list_decisions(store.DEMO_ID) == ()
    assert [c.case_id for c in seeded.get_folder(store.DEMO_ID).cards] == ["snap_no_receipt"]
    seeded.refresh_demo_matches(demo.match_plan())
    assert snapshot(seeded, store.DEMO_ID) == seed
    assert snapshot(seeded, other) == kept


@pytest.mark.parametrize("table", ["cards", "notes", "suggestions"])
def test_a_failed_reset_restores_the_complete_previous_seed(
    seeded: store.FolderStore, table: str
) -> None:
    seed = snapshot(seeded, store.DEMO_ID)
    with closing(sqlite3.connect(seeded.path)) as db:
        db.execute(
            f"CREATE TRIGGER fail_seed BEFORE INSERT ON {table}"
            " BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        seeded.refresh_demo_matches(demo.match_plan())
    with (
        pytest.raises(sqlite3.IntegrityError, match="injected"),
        seeded.visitor_write(store.DEMO_ID),
    ):
        pass  # copying the seed fails too, and leaves no half-made copy
    with closing(sqlite3.connect(seeded.path)) as db:
        db.execute("DROP TRIGGER fail_seed")
    assert snapshot(seeded, store.DEMO_ID) == seed
    assert len(rows(seeded.path, "SELECT * FROM folders")) == 1


def test_first_edit_copies_decisions_onto_the_copied_cards(
    seeded: store.FolderStore, client: TestClient
) -> None:
    seed = snapshot(seeded, store.DEMO_ID)
    card = seeded.get_folder(store.DEMO_ID).cards[0].id
    response = client.post(f"{SEED}/cards/{card}/status", data={"status": "done"})
    assert response.status_code == 303
    copy = response.headers["location"].removeprefix("/f/")
    assert copy != store.DEMO_ID
    copied = snapshot(seeded, copy)
    assert copied[2:] == seed[2:]  # notes and accepted decisions, on the copy's own cards
    copied_cards = {c.id for c in seeded.get_folder(copy).cards}
    decisions = seeded.list_decisions(copy)
    assert len(decisions) == 3 and {d.card_id for d in decisions} == copied_cards
    assert snapshot(seeded, store.DEMO_ID) == seed
    assert client.get(f"/f/{copy}/cards/{min(copied_cards)}/suggestions").text.count(HELD) == 3


def test_two_visitors_get_separate_copies_and_the_seed_stays(
    seeded: store.FolderStore, client: TestClient
) -> None:
    seed = snapshot(seeded, store.DEMO_ID)
    cards = seeded.get_folder(store.DEMO_ID).cards
    first = client.post(f"{SEED}/cards/{cards[0].id}/status", data={"status": "done"})
    second = client.post(f"{SEED}/cards/{cards[1].id}/priority", data={"priority": "low"})
    one, two = (r.headers["location"].removeprefix("/f/") for r in (first, second))
    assert len({one, two, store.DEMO_ID}) == 3
    assert seeded.get_folder(one).cards[0].status == "done"
    assert seeded.get_folder(two).cards[0].status == cards[0].status
    assert seeded.get_folder(two).cards[1].priority == "low"
    assert seeded.get_folder(one).cards[1].priority == cards[1].priority
    for copy in (one, two):
        assert snapshot(seeded, copy)[3] == seed[3]
    assert {c.id for c in seeded.get_folder(one).cards}.isdisjoint(
        c.id for c in seeded.get_folder(two).cards
    )
    assert snapshot(seeded, store.DEMO_ID) == seed
    seeded.refresh_demo_matches(demo.match_plan())
    assert seeded.get_folder(one).cards[0].status == "done"
    assert len(seeded.list_decisions(two)) == 3


def test_cli_matches_preview_writes_nothing_and_commit_seeds(
    client: TestClient, tmp_path: Path
) -> None:
    command = [sys.executable, "-m", "app.folders.demo", "--matches"]
    preview = subprocess.run(command, capture_output=True, text=True, check=True)
    assert not (tmp_path / "folders.db").exists()
    assert "--commit" in preview.stdout
    for seed in demo.match_plan():
        assert encode_match(seed.match) in preview.stdout
    subprocess.run([*command, "--commit"], capture_output=True, text=True, check=True)
    db = folder_store(tmp_path / "folders.db")
    assert len(db.list_decisions(store.DEMO_ID)) == 3
    before = rows(db.path, "SELECT * FROM folders")
    demo.main(["--matches"])
    assert rows(db.path, "SELECT * FROM folders") == before
