"""#395: schema-v1 match identities and atomic folder capacity."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.folders import store
from app.folders.references import decode_match, encode_match
from app.tools.matches import MatchReference
from etl.boundaries import DistrictId
from tests.regressions.test_wo153_safeguards import db, db_path, state

__all__ = ["db", "db_path"]
REFERENCE = MatchReference(
    district=DistrictId(chamber="house", district=22),
    population_id="disability",
    program_id="hawaii-able",
)


def test_empty_folder_match_restart_and_legacy_state(db: store.FolderStore, db_path: Path) -> None:
    folder = db.create_empty_folder("District outreach")
    assert db.get_folder(folder).cards == ()
    db.save_match(folder, REFERENCE)
    db.save_case(folder, "legacy_case", "senate", 3)
    match, legacy = db.get_folder(folder).cards
    db.set_priority(folder, match.id, "high", "Plan outreach")
    db.set_status(folder, match.id, "planned")
    db.add_note(folder, match.id, "Ask the agency about access.", True)
    db.save_match(folder, REFERENCE)
    restarted = store.FolderStore(db_path, state())
    saved = restarted.get_folder(folder)
    assert len(saved.cards) == 2
    assert saved.cards[0].id == match.id
    assert (saved.cards[0].priority, saved.cards[0].status) == ("high", "planned")
    assert saved.cards[0].reason == "Plan outreach"
    assert decode_match(saved.cards[0].case_id, "house", 22) == REFERENCE
    assert decode_match(legacy.case_id, "senate", 3) is None
    assert restarted.list_notes(folder)[0].body == "Ask the agency about access."
    assert len(store.MIGRATIONS) == 1


@pytest.mark.parametrize(
    "key",
    [
        "match:v2:disability:hawaii-able",
        "match:v1:bad%:snap",
        "match:v1:disability:snap?",
        "match:v1:disability:snap#",
        "match:v1:../:snap",
        "match:v1:disability:snap\n",
        "match:v1:disability",
        "match:v1:disability:snap:extra",
    ],
)
def test_malformed_match_keys_are_refused(key: str) -> None:
    with pytest.raises(ValueError, match="Invalid match key"):
        decode_match(key, "house", 22)


def test_match_district_is_validated() -> None:
    with pytest.raises(ValidationError, match="district"):
        decode_match(encode_match(REFERENCE), "senate", 26)


@pytest.mark.parametrize("kind", ["cards", "notes"])
def test_concurrent_capacity_and_duplicate_at_limit(db: store.FolderStore, kind: str) -> None:
    folder = db.create_folder("Outreach", "legacy_case", "house", 22)
    maximum = 200 if kind == "cards" else 1000
    if kind == "notes":
        db.save_case(folder, "second_case", "house", 22)
    cards = db.get_folder(folder).cards

    def write(number: int) -> bool:
        independent = store.FolderStore(db.path, state())
        try:
            if kind == "cards":
                independent.save_case(folder, f"case_{number}", "house", 22)
            else:
                independent.add_note(
                    folder, cards[number % len(cards)].id, "Agency follow-up", True
                )
        except store.CapacityError as error:
            assert kind in str(error)
            return False
        return True

    for number in range(maximum - (2 if kind == "cards" else 1)):
        assert write(number)
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(write, [maximum, maximum + 1])) == [False, True]
    assert len(db.get_folder(folder).cards if kind == "cards" else db.list_notes(folder)) == maximum
    db.save_case(folder, "legacy_case", "house", 22)
    other = db.create_folder("Another district", "legacy_case", "senate", 3)
    db.add_note(other, db.get_folder(other).cards[0].id, "Agency follow-up", True)
    if kind == "notes":
        note = db.list_notes(folder)[0]
        db.edit_note(folder, note.id, "Updated agency follow-up", True)
        db.delete_note(folder, note.id)
        assert write(maximum + 2)
    else:
        with pytest.raises(store.CapacityError, match="cards"):
            db.save_match(folder, REFERENCE)


def test_demo_copy_and_edit_roll_back_together(db: store.FolderStore) -> None:
    seed = store.DemoCard(
        case_id="legacy_case",
        priority="high",
        status="planned",
        body="Agency follow-up",
        dated="2026-11-08",
    )
    db.refresh_demo((seed,))
    original = db.get_folder(store.DEMO_ID).cards[0]
    with db.visitor_write(store.DEMO_ID) as copy:
        folder = copy.folder_id
        db.save_match(folder, REFERENCE)
    assert len(db.get_folder(folder).cards) == 2
    assert db.get_folder(folder).cards[0].priority == "high"
    assert db.list_notes(folder)[0].body == seed.body
    with (
        pytest.raises(RuntimeError, match="after writes"),
        db.visitor_write(store.DEMO_ID) as failed,
    ):
        db.save_match(failed.folder_id, REFERENCE)
        raise RuntimeError("after writes")
    with pytest.raises(store.FolderNotFoundError):
        db.get_folder(failed.folder_id)
    assert db.get_folder(store.DEMO_ID).cards == (original,)


@pytest.mark.parametrize("body", ["Call 808-555-1234", "Email office@example.gov"])
def test_public_contact_has_no_override(db: store.FolderStore, body: str) -> None:
    folder = db.create_folder("Outreach", "legacy_case", "house", 22)
    with pytest.raises(ValidationError, match="Personal phone numbers, emails and addresses"):
        db.add_note(folder, db.get_folder(folder).cards[0].id, body, True)
    assert db.list_notes(folder) == ()


def test_capacity_failure_rolls_back_demo_clone(db: store.FolderStore) -> None:
    db.refresh_demo(
        tuple(
            store.DemoCard(
                case_id=f"case_{n}",
                priority="normal",
                status="idea",
                body="Agency follow-up",
                dated="2026-11-08",
            )
            for n in range(200)
        )
    )
    with (
        pytest.raises(store.CapacityError, match="200 cards"),
        db.visitor_write(store.DEMO_ID) as copy,
    ):
        db.save_match(copy.folder_id, REFERENCE)
    with pytest.raises(store.FolderNotFoundError):
        db.get_folder(copy.folder_id)
    assert len(db.get_folder(store.DEMO_ID).cards) == 200


def test_match_save_requires_a_mutable_live_folder(db: store.FolderStore) -> None:
    with pytest.raises(store.FolderNotFoundError):
        db.save_match("0" * 32, REFERENCE)
    db.refresh_demo(())
    with pytest.raises(store.FolderNotFoundError):
        db.save_match(store.DEMO_ID, REFERENCE)


def test_empty_folder_validation_precedes_sqlite(
    db: store.FolderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise AssertionError("SQLite must not open")

    monkeypatch.setattr(db, "_connect", refuse)
    with pytest.raises(ValidationError, match="at least 1 character"):
        db.create_empty_folder("")


@pytest.mark.parametrize("kind", ["cards", "notes"])
def test_demo_refresh_limits_are_atomic(db: store.FolderStore, kind: str) -> None:
    seed = store.DemoCard(
        case_id="legacy_case",
        priority="high",
        status="done",
        body="Agency follow-up",
        dated="2026-11-08",
    )
    db.refresh_demo((seed,))
    original = db.get_folder(store.DEMO_ID)
    notes = db.list_notes(store.DEMO_ID)
    cards = (
        tuple(seed.model_copy(update={"case_id": f"case_{n}"}) for n in range(201))
        if kind == "cards"
        else (seed,) * 1001
    )
    with pytest.raises(store.CapacityError, match=kind):
        db.refresh_demo(cards)
    assert db.get_folder(store.DEMO_ID) == original
    assert db.list_notes(store.DEMO_ID) == notes
