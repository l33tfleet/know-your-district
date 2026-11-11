"""WO303: shared brief copy and identical SNAP readings, referrals and source links."""

from pathlib import Path

import pytest
import yaml  # noqa: F401  # pyright: ignore[reportUnusedImport]  # used only by tests #187 superseded
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
from playwright.sync_api import Route, sync_playwright

import app.copy
import app.main
import app.web.snap
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


def test_one_partial_edit_reaches_both_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = configure(tmp_path, monkeypatch, "off")
    name = "partials/snap-readings.html"
    # Change the shared template without changing either wrapper. A duplicated
    # table/referral block would keep its old output and fail this assertion.
    replacement = "<table><caption>Shared table edit</caption></table><p>Shared referral edit</p>"
    for templates in (app.main.templates, app.web.snap.templates):
        loader = templates.env.loader
        assert loader is not None
        monkeypatch.setattr(
            templates.env, "loader", ChoiceLoader([DictLoader({name: replacement}), loader])
        )
    for surface in surfaces(client):
        assert surface.one("caption").text == "Shared table edit"
        assert surface.find_all("p")[-1].text == "Shared referral edit"


def test_shared_partial_accepts_omitted_source_links() -> None:
    root = Path(__file__).resolve().parents[2] / "templates"
    environment = Environment(loader=FileSystemLoader(root), undefined=StrictUndefined)
    template = environment.get_template("partials/snap-readings.html")
    result = snap.load_result(DistrictId(chamber="house", district=22))
    context = {
        "result": result,
        "readings": (result.district, *result.counties, result.state),
        "labels": app.copy.section_copy("figures"),
        **{
            field: app.copy.section_copy("snap_question")[field]
            for field in ("caption", "estimate_label", "official_label", "referral_label")
        },
    }
    omitted = parse(template.render(context))
    assert_same(omitted, parse(template.render(context, source_links={})))
    assert [link.attrs["href"] for link in omitted.find_all("a")] == [
        result.official_url,
        result.referral_url,
    ]


def test_story_step_four_exposes_the_official_next_step() -> None:
    """The shipped SNAP case presents the story's named link beside its evidence."""
    client = TestClient(asgi_app)
    result = snap.load_result(DistrictId(chamber="house", district=22))

    def fulfil(route: Route) -> None:
        response = client.get(route.request.url.replace("http://kyd", ""))
        route.fulfill(
            body=response.content,
            status=response.status_code,
            content_type=response.headers["content-type"],
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("http://kyd/**", fulfil)
        page.goto("http://kyd/brief/house/22")
        case = page.get_by_role("region", name="SNAP").filter(has=page.locator(".case-next"))
        assert case.count() == 1
        text = case.inner_text()
        assert result.district.value_text in text
        assert result.district.moe_text in text
        assert result.district.reliability_word in text
        assert "not current enrollment" in text
        assert "DHS decides eligibility" in text
        next_step = case.get_by_role("link", name="official next step", exact=True)
        assert next_step.count() == 1
        assert next_step.is_visible()
        assert next_step.get_attribute("href") == result.official_url
        browser.close()
