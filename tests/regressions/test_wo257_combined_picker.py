"""WO257: one picker control, so the chamber and the district number can never disagree.

Replaces `test_wo97_brief_page.py::test_home_picker_is_a_plain_get_form_with_chamber_and_number`
and `::test_picker_htmx_enhancement_uses_2x_attributes`. The home picker is one `<select
id="chamber" name="d">` with a House and a Senate `<optgroup>`; options are `house-1`..`house-51`
and `senate-1`..`senate-25`. It makes no htmx request of its own (so Back or a failed partial
cannot leave two controls out of step); the form keeps htmx 2.x `hx-boost`. `/brief` accepts the
combined `d` and still accepts the old `chamber` + `n` pair.
"""

import pytest
from fastapi.testclient import TestClient

from tests.regressions.test_wo97_brief_page import brief, client, facts_db, parse, picker_form

__all__ = ["client", "facts_db"]


def test_home_picker_is_one_control_with_51_house_and_25_senate_choices(
    client: TestClient,
) -> None:
    form = picker_form(client)
    assert form.attrs.get("method", "get").lower() == "get"
    assert form.find_all("button", type="submit")
    selects = form.find_all("select")
    assert len(selects) == 1
    select = selects[0]
    assert select.attrs["id"] == "chamber"
    assert select.attrs["name"] == "d"
    groups = select.find_all("optgroup")
    assert [g.attrs["label"] for g in groups] == [
        "State House: districts 1–51",
        "State Senate: districts 1–25",
    ]
    house = [o.attrs["value"] for o in groups[0].find_all("option")]
    senate = [o.attrs["value"] for o in groups[1].find_all("option")]
    assert house == [f"house-{n}" for n in range(1, 52)]
    assert senate == [f"senate-{n}" for n in range(1, 26)]
    assert len(select.find_all("option")) == 51 + 25
    texts = {o.attrs["value"]: o.text for o in select.find_all("option")}
    assert texts["senate-7"] == "Senate District 7"
    assert texts["house-22"] == "House District 22"
    labels = [lab for lab in form.find_all("label") if lab.attrs.get("for") == "chamber"]
    assert len(labels) == 1 and labels[0].text.strip()
    # No second control that could disagree with the first.
    assert not form.find_all("select", name="n")
    assert not form.find_all("select", name="chamber")


def test_picker_makes_no_htmx_request_and_the_form_keeps_2x_boost(client: TestClient) -> None:
    form = picker_form(client)
    assert form.attrs.get("hx-boost") == "true"
    for node in [form, *form.find_all()]:
        hx = [a for a in node.attrs if a.startswith(("hx-", "data-hx-"))]
        if node is form:
            assert hx == ["hx-boost"]
        else:
            assert hx == [], f"{node.tag} carries {hx}"
    # htmx 4 renamed/added attributes; none may appear.
    assert not [a for a in form.attrs if a.startswith(("hx-action", "hx-method", "hx-status"))]
    assert "/picker/numbers" not in client.get("/").text


@pytest.mark.parametrize(
    ("d", "location", "heading"),
    [
        ("senate-7", "/brief/senate/7", "Senate District 7"),
        ("house-22", "/brief/house/22", "House District 22"),
        ("house-51", "/brief/house/51", "House District 51"),
        ("senate-25", "/brief/senate/25", "Senate District 25"),
    ],
)
def test_combined_choice_redirects_to_its_brief(
    client: TestClient, d: str, location: str, heading: str
) -> None:
    response = client.get("/brief", params={"d": d}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == location
    assert heading in brief(client, location).one("h1").text


def test_combined_choice_wins_over_the_legacy_pair(client: TestClient) -> None:
    response = client.get(
        "/brief", params={"d": "senate-7", "chamber": "house", "n": "22"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/brief/senate/7"


def test_legacy_chamber_and_number_still_redirect(client: TestClient) -> None:
    response = client.get("/brief", params={"chamber": "senate", "n": "5"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/brief/senate/5"


@pytest.mark.parametrize(
    "d",
    [
        "senate-26",  # beyond the Senate
        "house-52",  # beyond the House
        "house-0",
        "assembly-1",  # unknown chamber
        "House-1",  # chambers are lower case
        "house-2a",  # not digits
        "house-",
        "house",
        "senate-7-1",
        " senate-7",
        "senate-" + chr(0x0667),  # ARABIC-INDIC DIGIT SEVEN: digits are ASCII only
        "house-07",  # no leading zero
    ],
)
def test_bad_combined_choice_is_html_404(client: TestClient, d: str) -> None:
    response = client.get("/brief", params={"d": d}, follow_redirects=False)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "/" in [a.attrs.get("href") for a in parse(response.text).find_all("a")]


@pytest.mark.parametrize("control", ["\n", "\t", "\x00", "\r", "\x7f"], ids=repr)
@pytest.mark.parametrize(
    "where",
    ["|senate-7", "senate-7|", "senate|-7", "senate-|7"],
    ids=["leading", "trailing", "embedded-dash", "embedded-digit"],
)
def test_combined_choice_with_control_characters_is_html_404(
    client: TestClient, control: str, where: str
) -> None:
    """Raw control characters are rejected as they arrive, never stripped into `senate-7`."""
    d = where.replace("|", control)
    assert d.replace(control, "") == "senate-7"
    response = client.get("/brief", params={"d": d}, follow_redirects=False)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "location" not in response.headers


def test_picker_numbers_partial_stays_available(client: TestClient) -> None:
    response = client.get("/picker/numbers", params={"chamber": "senate"})
    assert response.status_code == 200
