"""WO303: shared brief copy and identical SNAP readings, referrals and source links."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.copy
from app import features, snap
from app.main import app as asgi_app
from app.source_links import source_links
from etl.boundaries import DistrictId
from tests.regressions.test_wo97_brief_page import Node, parse


def assert_same(left: Node, right: Node) -> None:
    assert (left.tag, left.attrs, left.text) == (right.tag, right.attrs, right.text)
    assert len(left.children) == len(right.children)
    for first, second in zip(left.children, right.children, strict=True):
        assert_same(first, second)


def surfaces(client: TestClient, query: str = "") -> tuple[Node, Node]:
    card = client.get(f"/brief/house/22?{query}")
    answer = client.get(f"/brief/house/22/snap-answer?question=no_snap_households&{query}")
    assert card.status_code == answer.status_code == 200
    return (
        parse(card.text).one("section", class_="outreach"),
        parse(answer.text).one("section", class_="snap-answer"),
    )


def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str) -> TestClient:
    path = tmp_path / "features.toml"
    path.write_text(f'outreach = "on"\nsnap_question = "on"\nsource_links = "{status}"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    return TestClient(asgi_app)


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
    assert card.one("h2").text == "Households in poverty reporting no SNAP receipt"
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


@pytest.mark.parametrize(
    ("status", "query", "visible"),
    [("off", "", False), ("on", "", True), ("preview", "", False), ("preview", "preview=1", True)],
)
@pytest.mark.parametrize("missing", [False, True])
def test_readings_and_referrals_match_with_optional_source_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    query: str,
    visible: bool,
    missing: bool,
) -> None:
    client = configure(tmp_path, monkeypatch, status)
    if missing:
        monkeypatch.setattr(snap, "SNAP_DB", tmp_path / "absent.db")
    result = snap.load_result(DistrictId(chamber="house", district=22))
    card, answer = surfaces(client, query)
    assert_same(card.one("table"), answer.one("table"))
    assert_same(card.find_all("p")[-1], answer.find_all("p")[-1])
    expected = [result.official_url, result.referral_url]
    if visible:
        expected = [
            link.url
            for reading in (result.district, *result.counties, result.state)
            if reading.fact is not None
            for link in source_links(reading.fact)
        ] + expected
    for surface in (card, answer):
        assert [link.attrs["href"] for link in surface.find_all("a")] == expected
