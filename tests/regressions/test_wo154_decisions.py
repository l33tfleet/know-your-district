"""#405 (step 1 of #154): v2 keeps atomic suggestion decisions; v1 records stay unchanged."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.folders import store
from app.folders.references import decode_match
from app.suggestions import SuggestionReference
from app.tools.matches import MatchReference
from etl.boundaries import DistrictId
from tests.regressions import test_wo224_setup as setup
from tests.regressions.test_wo153_safeguards import Clock, clock, db, db_path
from tests.regressions.test_wo224_setup import LIMIT, VERSION, capped, scalar, state

__all__ = ["clock", "db", "db_path"]
V1, V2 = (Path(store.__file__).with_name(n).read_text() for n in ("schema.sql", "suggestions.sql"))
HOUSE_22 = DistrictId(chamber="house", district=22)
REFERENCE = MatchReference(district=HOUSE_22, population_id="disability", program_id="able")
ONE = SuggestionReference(match=REFERENCE, source="district_matches", dated=date(2026, 11, 9))
TWO = ONE.model_copy(update={"match": REFERENCE.model_copy(update={"program_id": "snap"})})
DEMO = store.DemoCard(case_id="demo", priority="low", status="done", body="N", dated="2026-11-08")
COUNT = "SELECT count(*) FROM suggestions"


def dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as db:
        return [line for line in db.iterdump() if "suggestions" not in line]


def populate_v1(path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, int]:
    with monkeypatch.context() as v1:
        v1.setattr(store, "MIGRATIONS", store.MIGRATIONS[:1])
        folders = capped(path, 8 * LIMIT)
        folder = folders.create_folder("Kalihi outreach", "legacy_case", "house", 22)
        folders.save_match(folder, REFERENCE)
        card = folders.get_folder(folder).cards[1].id
        folders.set_priority(folder, card, "high", "Plan outreach")
        folders.set_status(folder, card, "contacted")
        folders.add_note(folder, card, "Ask the agency about access.", True)
        folders.refresh_demo((DEMO,))
        folders.spend_rate((store.RateRule(scope="saves", limit=5, window_seconds=60),))
    return folder, card


def test_empty_folder_match_restart_and_legacy_state(db: store.FolderStore) -> None:
    folder = db.create_empty_folder("District outreach")
    assert db.get_folder(folder).cards == ()
    db.save_match(folder, REFERENCE)
    db.save_case(folder, "legacy_case", "senate", 3)
    match, legacy = db.get_folder(folder).cards
    db.set_priority(folder, match.id, "high", "Plan outreach")
    db.set_status(folder, match.id, "planned")
    db.add_note(folder, match.id, "Ask the agency about access.", True)
    db.save_match(folder, REFERENCE)
    restarted = store.FolderStore(db.path, state())
    saved = restarted.get_folder(folder)
    assert len(saved.cards) == 2
    assert saved.cards[0].id == match.id
    assert (saved.cards[0].priority, saved.cards[0].status) == ("high", "planned")
    assert saved.cards[0].reason == "Plan outreach"
    assert decode_match(saved.cards[0].case_id, "house", 22) == REFERENCE
    assert decode_match(legacy.case_id, "senate", 3) is None
    assert restarted.list_notes(folder)[0].body == "Ask the agency about access."
    assert store.MIGRATIONS == (V1, V2) and "'contacted'" in V1 and "'planned'" in V1
    assert all("'in_progress'" not in step for step in store.MIGRATIONS)


LATE = {
    "error": ("INSERT INTO no_such VALUES (1);", sqlite3.OperationalError, "no_such"),
    "capacity": ("INSERT INTO bulky VALUES (zeroblob(1048576));", store.CapacityError, "size"),
}


@pytest.mark.parametrize("base", ["v1", "latest"])
@pytest.mark.parametrize("late", LATE)
def test_failed_migration_rolls_back_whole(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, base: str, late: str
) -> None:
    """Replaces test_wo224_setup.py's v1-pinned failure and past-the-ceiling tests."""
    script, error, message = LATE[late]
    script = "CREATE TABLE half (id INTEGER); CREATE TABLE bulky (b BLOB); " + script
    limit = 8 * LIMIT if base == "v1" else LIMIT
    if base == "v1":
        populate_v1(db_path, monkeypatch)
        monkeypatch.setattr(store, "MIGRATIONS", (V1, V2 + script))  # fails after v2's writes
    else:
        capped(db_path).initialize()
        setup.add_folders(db_path, range(1))
        setup.add_migration(monkeypatch, script)
    before, version = dump(db_path), scalar(db_path, VERSION)
    with pytest.raises(error, match=message):
        capped(db_path, limit).initialize()
    assert version == len(store.MIGRATIONS) - 1
    assert (scalar(db_path, VERSION), dump(db_path)) == (version, before)
    tables = ("half", "bulky", "suggestions")[: 3 if base == "v1" else 2]
    assert not any(setup.has_table(db_path, table) for table in tables)
    assert setup.db_bytes(db_path) <= limit


def test_populated_v1_migrates_unchanged(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder, card = populate_v1(db_path, monkeypatch)
    before, folders = dump(db_path), capped(db_path, 8 * LIMIT)
    view = (folders.get_folder(folder), folders.list_notes(folder))
    for _ in range(2):
        capped(db_path, 8 * LIMIT).initialize()
        assert (scalar(db_path, VERSION), dump(db_path)) == (2, before)
    assert (folders.get_folder(folder), folders.list_notes(folder)) == view
    folders.decide(folder, ONE, "accepted")  # the saved match card is the accepted next step
    assert folders.get_folder(folder) == view[0]
    assert [(d.reference, d.card_id) for d in folders.list_decisions(folder)] == [(ONE, card)]


def test_pending_migration_cannot_spend_free_pages_past_the_ceiling(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capped(db_path, 8 * LIMIT).initialize()
    latest = len(store.MIGRATIONS)
    setup.add_folders(db_path, range(2000))
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("DELETE FROM folders WHERE rowid > 1")
    assert scalar(db_path, "PRAGMA freelist_count") > 8
    assert (size := setup.db_bytes(db_path)) > LIMIT
    capped(db_path).initialize()  # past its ceiling with nothing to migrate, it still opens
    setup.add_migration(monkeypatch, "CREATE TABLE small (id INTEGER);")
    with pytest.raises(store.CapacityError, match="cannot enforce"):
        capped(db_path).initialize()
    assert (scalar(db_path, VERSION), setup.has_table(db_path, "small")) == (latest, False)
    assert (scalar(db_path, setup.FOLDERS), setup.db_bytes(db_path)) == (1, size)
    capped(db_path, 8 * LIMIT).initialize()  # refused, not stuck: a fitting limit migrates
    capped(db_path, 8 * LIMIT).initialize()  # a second run would fail on CREATE TABLE
    assert (scalar(db_path, VERSION), setup.has_table(db_path, "small")) == (latest + 1, True)


def test_decisions_keep_one_card_and_roll_back_whole(db: store.FolderStore) -> None:
    folder, other = db.create_empty_folder("One"), db.create_empty_folder("Two")
    db.decide(folder, ONE, "dismissed")
    (first,) = db.list_decisions(folder)
    assert (first.card_id, first.updated_at) == (None, first.created_at)  # no card yet
    db.decide(folder, ONE, "accepted")
    (card,) = db.get_folder(folder).cards
    assert (decode_match(card.case_id, "house", 22), card.status) == (REFERENCE, "idea")
    db.set_status(folder, card.id, "contacted")
    db.add_note(folder, card.id, "Agency follow-up", True)
    cards = db.get_folder(folder).cards
    for decision in ("accepted", "accepted", "dismissed"):
        db.decide(folder, ONE, decision)
    db.decide(folder, TWO, "dismissed")
    db.decide(other, ONE, "dismissed")  # folders are isolated
    one, two = store.FolderStore(db.path, state()).list_decisions(folder)
    assert (one.reference, one.decision, one.card_id) == (ONE, "dismissed", card.id)
    assert (one.created_at, two.reference, two.card_id) == (first.created_at, TWO, None)
    assert (db.get_folder(folder).cards, len(db.list_notes(folder))) == (cards, 1)
    assert [(d.reference, d.decision) for d in db.list_decisions(other)] == [(ONE, "dismissed")]
    assert (db.get_folder(other).cards, scalar(db.path, COUNT)) == ((), 3)
    db.refresh_demo(())
    for folder in ("0" * 32, store.DEMO_ID):
        with pytest.raises(store.FolderNotFoundError):
            db.decide(folder, ONE, "accepted")
    folder = db.create_empty_folder("Full folder")
    for number in range(200):
        db.save_case(folder, f"case_{number}", "house", 22)
    full = db.get_folder(folder)
    with pytest.raises(store.CapacityError, match="200 cards"):
        db.decide(folder, ONE, "accepted")
    assert (db.list_decisions(folder), scalar(db.path, COUNT)) == ((), 3)
    assert db.get_folder(folder) == full


def test_bad_input_is_refused_first(db: store.FolderStore, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = db.create_empty_folder("District outreach")
    monkeypatch.setattr(db, "_connect", lambda: pytest.fail("SQLite must not open"))
    for field, value, error in (
        ("decision", "maybe", "'accepted' or 'dismissed'"),
        ("source", "chat", "'district_matches'"),
        ("dated", "2026-13-01", "month"),
    ):
        ref = ONE.model_dump() | ({} if field == "decision" else {field: value})
        with pytest.raises(ValidationError, match=error) as refused:
            db.decide(folder, ref, value if field == "decision" else "accepted")  # pyright: ignore[reportArgumentType] -- untrusted input
        assert refused.value.error_count() == 1  # only the one check fired


def test_clone_rotation_and_expiry_carry_decisions(db: store.FolderStore, clock: Clock) -> None:
    db.refresh_demo((DEMO,))
    with db.visitor_write(store.DEMO_ID) as copy:
        db.decide(copy.folder_id, ONE, "accepted")
    with pytest.raises(RuntimeError), db.visitor_write(store.DEMO_ID) as failed:
        db.decide(failed.folder_id, ONE, "accepted")
        raise RuntimeError("after writes")
    with pytest.raises(store.FolderNotFoundError):
        db.list_decisions(failed.folder_id)
    assert (len(db.get_folder(copy.folder_id).cards), db.list_decisions(store.DEMO_ID)) == (2, ())
    decided, rotated = db.list_decisions(copy.folder_id), db.rotate_link(copy.folder_id)
    assert (len(decided), db.list_decisions(rotated)) == (1, decided)
    with pytest.raises(store.FolderNotFoundError):
        db.decide(copy.folder_id, TWO, "accepted")
    clock.advance(days=181)
    with pytest.raises(store.FolderNotFoundError):
        db.list_decisions(rotated)
    db.purge_expired()
    assert scalar(db.path, COUNT) == 0
