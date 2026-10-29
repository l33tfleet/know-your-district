"""WO162 (step 5 of #136): a gated SNAP question form and a deterministic answer route.

The answer reads the same SNAP result as the outreach card through a tool, with no model
call: every estimate, margin of error, reliability word, citation and note in the answer
matches the card (which prints unchanged). Missing data keeps the card's wording. The
feature ships off; "preview" shows it only with ?preview=1, and a disabled route is a 404.
"""

import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from playwright.sync_api import Route, sync_playwright

import app.copy
from app import features, snap
from app.main import app as asgi_app
from etl.boundaries import DistrictId
from tests.regressions.test_wo97_brief_page import Node, parse
from tests.regressions.test_wo122_browser_checks import axe_problems

ROOT = Path(__file__).resolve().parents[2]
COPY = yaml.safe_load(app.copy.COPY_PATH.read_text(encoding="utf-8"))
FLAG = "snap_question"

Configure = Callable[[str], TestClient]


@pytest.fixture
def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Configure:
    def write(text: str) -> TestClient:
        path = tmp_path / "features.toml"
        path.write_text('outreach = "on"\n' + text)
        monkeypatch.setattr(features, "FEATURES_PATH", path)
        return TestClient(asgi_app)

    return write


def card(client: TestClient, path: str = "/brief/house/22") -> Node:
    response = client.get(path)
    assert response.status_code == 200
    return parse(response.text).one("section", class_="outreach")


def answer(client: TestClient, path: str = "/brief/house/22", query: str = "") -> Node:
    response = client.get(f"{path}/snap-answer?question=no_snap_households{query}")
    assert response.status_code == 200
    return parse(response.text).one("section", class_="snap-answer")


def flat(node: Node) -> str:
    # Word-break elements split parser chunks without adding visible spaces.
    return " ".join("".join(node.parts).split())


def rows(node: Node) -> list[Node]:
    return node.one("tbody").find_all("tr")


def test_shipped_configuration_leaves_the_question_off() -> None:
    client = TestClient(asgi_app)
    assert features.validate_features()[FLAG] == features.Status.OFF
    for query in ("", "?preview=1"):
        assert "snap-question" not in client.get(f"/brief/house/22{query}").text
        response = client.get(f"/brief/house/22/snap-answer?question=no_snap_households{query}")
        assert response.status_code == 404


@pytest.mark.parametrize("path", ["/brief/house/22", "/brief/house/1", "/brief/senate/7"])
def test_answer_matches_card_estimates_wording_and_citations(
    configure: Configure, path: str
) -> None:
    client = configure(f'{FLAG} = "on"\n')
    expected = card(client, path)
    found = answer(client, path)
    chamber, number = path.split("/")[2:]
    result = snap.load_result(DistrictId.model_validate({"chamber": chamber, "district": number}))
    readings = [result.district, *result.counties, result.state]
    assert len(rows(found)) == len(readings)
    for card_row, answer_row, reading in zip(rows(expected), rows(found), readings, strict=True):
        assert answer_row.one("th", scope="row").text == card_row.one("th").text
        assert answer_row.one("td").one("p").text == card_row.one("td").one("p").text
        assert flat(answer_row.one("dl")) == flat(card_row.one("dl"))
        # Golden: the published row, unchanged.
        fact = reading.fact
        assert fact is not None and fact.value is not None and fact.moe is not None
        text = answer_row.one("td").one("p").text
        assert f"{fact.value:,.0f} households; ±{fact.moe:,.0f}; {reading.reliability_word}" in text
        for field in ("source", "table_id", "vintage", "geography", "method", "endpoint"):
            assert str(getattr(fact, field)) in flat(answer_row.one("dl"))
    in_cells = [id(p) for td in expected.find_all("td") for p in td.find_all("p")]
    card_notes = [p.text for p in expected.find_all("p") if id(p) not in in_cells]
    assert len(card_notes) == 4
    answer_text = found.text
    for note in card_notes:
        assert note in answer_text
    assert found.one("h3").text == expected.one("h2").text
    assert "eligible for" not in answer_text
    assert "qualify" not in answer_text.casefold()
    hrefs = [a.attrs.get("href") for a in found.find_all("a")]
    assert result.official_url in hrefs and result.referral_url in hrefs


def test_answer_is_deterministic_and_reads_through_the_tool(
    configure: Configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools import snap as tool

    client = configure(f'{FLAG} = "on"\n')
    seen: list[str] = []
    original = snap.load_result

    def spy(district: DistrictId) -> snap.SnapResult:
        seen.append(district.fact_key)
        return original(district)

    monkeypatch.setattr(snap, "load_result", spy)
    first = client.get("/brief/house/22/snap-answer?question=no_snap_households").text
    second = client.get("/brief/house/22/snap-answer?question=no_snap_households").text
    assert first == second
    assert seen == ["house:15:022:2022", "house:15:022:2022"]
    district = DistrictId(chamber="house", district=22)
    assert tool.DistrictSnap(district).answer().result == original(district)


@pytest.mark.parametrize("missing", ["database", "row", "estimate", "moe", "referrals"])
def test_missing_inputs_answer_with_the_card_wording(
    configure: Configure, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    database = tmp_path / "facts.db"
    if missing != "database":
        shutil.copyfile(snap.SNAP_DB, database)
        with sqlite3.connect(database) as db:
            geography = "house:15:022:2022"
            if missing == "row":
                db.execute("DELETE FROM facts WHERE geography = ?", [geography])
            elif missing in {"estimate", "moe"}:
                column = "moe" if missing == "moe" else "value"
                flag = "unavailable" if missing == "estimate" else "caution"
                db.execute(
                    f"UPDATE facts SET {column} = NULL, cv = NULL, reliability = ? "
                    "WHERE geography = ?",
                    [flag, geography],
                )
    monkeypatch.setattr(snap, "SNAP_DB", database)
    if missing == "referrals":
        monkeypatch.setattr(snap, "REFERRALS_PATH", tmp_path / "absent.json")
    client = configure(f'{FLAG} = "on"\n')
    expected = card(client)
    found = answer(client)
    first = rows(found)[0]
    assert first.one("td").text == rows(expected)[0].one("td").text
    if missing in {"database", "row"}:
        assert "No published figure in the fact table yet." in first.text
        assert "not available" in first.text
    elif missing == "estimate":
        assert "not available" in first.text
    elif missing == "moe":
        assert "no margin of error published" in first.text
        assert "use with caution" in first.text
    hrefs = [a.attrs.get("href") for a in found.find_all("a")]
    assert "https://humanservices.hawaii.gov/bessd/snap/" in hrefs
    assert "https://auw211.org/" in hrefs


def test_off_hides_form_and_route_and_skips_result_load(
    configure: Configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = configure(f'{FLAG} = "off"\n')
    calls: list[DistrictId] = []
    original = snap.load_result

    def counted(district: DistrictId) -> snap.SnapResult:
        calls.append(district)
        return original(district)

    monkeypatch.setattr(snap, "load_result", counted)
    for query in ("", "&preview=1"):
        page = client.get(f"/brief/house/22?v=a{query}")
        assert page.status_code == 200
        assert not parse(page.text).find_all("section", class_="snap-question")
        response = client.get(f"/brief/house/22/snap-answer?question=no_snap_households{query}")
        assert response.status_code == 404
        assert "text/html" in response.headers["content-type"]
    # Hidden even when the question itself is unknown: off never reveals the route.
    assert client.get("/brief/house/22/snap-answer?question=other").status_code == 404
    # Only the outreach card loaded the result; the answer route never did.
    assert len(calls) == 2


def test_preview_shows_form_and_answer_only_with_preview(configure: Configure) -> None:
    client = configure(f'{FLAG} = "preview"\n')
    assert not parse(client.get("/brief/house/22").text).find_all("section", class_="snap-question")
    assert client.get("/brief/house/22/snap-answer?question=no_snap_households").status_code == 404
    page = parse(client.get("/brief/house/22?preview=1&v=b").text)
    form = page.one("section", class_="snap-question").one("form")
    assert form.attrs["action"] == "/brief/house/22/snap-answer"
    assert form.attrs["method"] == "get"
    assert form.attrs["hx-get"] == "/brief/house/22/snap-answer"
    assert form.attrs["hx-target"] == "#snap-answer"
    hidden = {i.attrs["name"]: i.attrs["value"] for i in form.find_all("input", type="hidden")}
    assert hidden == {"question": "no_snap_households", "preview": "1", "v": "b"}
    question = COPY["sections"]["snap_question"]["question"]
    assert question in page.one("section", class_="snap-question").text
    found = answer(client, query="&preview=1&v=b")
    assert found.find_all("tbody")


def test_answer_route_validates_its_inputs(configure: Configure) -> None:
    client = configure(f'{FLAG} = "on"\n')
    response = client.get("/brief/house/22/snap-answer?question=other")
    assert response.status_code == 422
    assert "no_snap_households" in response.text
    assert client.get("/brief/house/22/snap-answer").status_code == 422
    for path in ("/brief/house/99", "/brief/mayor/1", "/brief/house/22x"):
        assert client.get(f"{path}/snap-answer?question=no_snap_households").status_code == 404
    query = "question=no_snap_households&preview=2"
    assert client.get(f"/brief/house/22/snap-answer?{query}").status_code == 404
    assert (
        client.get("/brief/house/22/snap-answer?question=no_snap_households&v=..").status_code
        == 404
    )


def test_form_is_screen_only_and_answer_arrives_by_htmx(configure: Configure) -> None:
    client = configure(f'{FLAG} = "on"\n')
    page_html = parse(client.get("/brief/house/22").text)
    wrapper = next(d for d in page_html.find_all("div", class_="screen-only") if d.find_all("form"))
    assert wrapper.one("section", class_="snap-question")

    def fulfil(route: Route) -> None:
        url = route.request.url.replace("http://kyd", "")
        types = {".css": "text/css", ".js": "text/javascript"}
        kind = next((t for ext, t in types.items() if url.endswith(ext)), "text/html")
        route.fulfill(body=client.get(url).content, content_type=kind)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 900})
        page.route("http://kyd/**", fulfil)
        page.goto("http://kyd/brief/house/22")
        page.locator(".snap-question button").click()
        page.locator("#snap-answer .snap-answer").wait_for()
        assert page.url == "http://kyd/brief/house/22"
        assert axe_problems(page) == []
        district = snap.load_result(DistrictId(chamber="house", district=22)).district
        assert district.value_text in page.locator("#snap-answer").inner_text()
        page.emulate_media(media="print")
        assert page.locator(".snap-question").count() == 1
        assert not page.locator(".snap-question").is_visible()
        browser.close()
