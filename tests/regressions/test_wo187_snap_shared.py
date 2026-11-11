"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

from pathlib import Path

import pytest
import yaml

import app.copy
from tests.regressions.test_wo303_snap_shared_rendering import configure, surfaces

__all__ = ["configure", "surfaces"]


# Replaces test_wo303_snap_shared_rendering.py::test_card_preserves_its_original_wording (wording only, #187).
def test_card_preserves_its_original_wording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = configure(tmp_path, monkeypatch, "off")
    card, _ = surfaces(client)
    assert card.one("h2").text == "Households in poverty that say they got no SNAP"
    # Fixed pre-consolidation copy: matching each other alone would allow both
    # surfaces to drift together and miss the unchanged-card acceptance rule.
    assert [child.text for child in card.children if child.tag == "p"] == [
        "ACS asks if a household got SNAP in the past 12 months. This is not current "
        "enrollment or eligibility. This published joint cell counts households with income "
        "under the poverty threshold that reported no Food Stamps/SNAP in that time.",
        "Survey answers undercount benefit receipt. A household that says it got none may "
        "still have had some.",
        "ACS uses national Census poverty thresholds. They are lower than the Hawaiʻi HHS "
        "poverty guidelines. This count does not decide who is eligible. It does not find "
        "households that could get SNAP but are not enrolled.",
        "SNAP may help. DHS decides eligibility. Contact DHS or Aloha United Way 211 for "
        "assistance. Official SNAP program page Aloha United Way 211",
    ]


# Replaces test_wo303_snap_shared_rendering.py::test_explicit_brief_copy_survives_canonical_rewording (wording only, #187).
def test_explicit_brief_copy_survives_canonical_rewording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = configure(tmp_path, monkeypatch, "off")
    copy = app.copy.load_copy()
    canonical = copy["sections"]["snap"]
    for field in ("heading", "measure_note", "poverty_note"):
        canonical[field] = "Reworded canonical measure: households eligible for assistance."
    path = tmp_path / "copy.yaml"
    path.write_text(yaml.safe_dump(copy, allow_unicode=True))
    monkeypatch.setattr(app.copy, "COPY_PATH", path)
    card, answer = surfaces(client)
    assert "eligible for" not in card.text
    assert "eligible for" not in answer.text
    assert card.one("h2").text == "Households in poverty that say they got no SNAP"
    # Copy edits reach both surfaces without another Python wording rewrite.
    expected = {
        "heading": "Shared outreach heading",
        "measure_note": "Shared measure caveat",
        "poverty_note": "Shared poverty caveat",
    }
    canonical["brief"] = expected
    labels = copy["sections"]["snap_question"]
    for field in ("caption", "estimate_label", "official_label", "referral_label"):
        labels[field] = f"Shared {field}"
    path.write_text(yaml.safe_dump(copy, allow_unicode=True))
    from app.snap import brief_wording

    wording = brief_wording()
    assert wording.heading == expected["heading"]
    assert wording.measure_note == expected["measure_note"]
    assert wording.poverty_note == expected["poverty_note"]
    for surface in surfaces(client):
        for value in expected.values():
            assert value in surface.text
        for field in ("caption", "estimate_label", "official_label", "referral_label"):
            assert labels[field] in surface.text
