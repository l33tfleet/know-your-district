"""#382: the saved case's figure is checked where it renders, not anywhere in the page's HTML.

The test this replaces searched the whole page for the published count, so a random folder id
that happened to contain those digits (the reported `8f00010abc7d73c9d8a36773fad03623` holds
`773`) read as a stale count. Here the folder id is forced to that collision and the count is
read from the saved case's own count paragraph.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import snap
from app.folders import store
from etl.boundaries import DistrictId
from tests.regressions.test_journey_folder_save import COPY, client, create, flag
from tests.regressions.test_wo97_brief_page import Node, parse

# Reuse the folder-journey fixtures unchanged.
__all__ = ["client", "flag"]

COLLISION = "8f00010abc7d73c9d8a36773fad03623"
DISTRICT = DistrictId(chamber="house", district=22)


def case_section(html: str) -> Node:
    return parse(html).one("section", class_="case")


def test_a_new_figure_shows_on_the_next_render(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folder keeps no figure, so a rebuilt fact table changes the saved case."""
    monkeypatch.setattr(store, "new_folder_id", lambda: COLLISION)
    path = create(client)
    assert path == f"/f/{COLLISION}"

    result = snap.load_result(DISTRICT)
    published = result.district.value_text
    first = client.get(path).text
    assert published in case_section(first).one("p", class_="case-reading").text

    monkeypatch.setattr(snap, "SNAP_DB", tmp_path / "absent.db")
    html = client.get(path).text
    # The collision is still on the page, so only the case itself can tell the count is gone.
    assert COLLISION in html and published in COLLISION
    shown = case_section(html)
    assert shown.find_all("p", class_="case-reading") == []
    assert published not in shown.text
    unavailable = COPY["unavailable"].format(district=result.district.geography_name)
    assert shown.one("p", class_="case-unavailable").text == " ".join(unavailable.split())
