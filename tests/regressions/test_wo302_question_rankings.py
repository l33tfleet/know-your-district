"""WO #302: two fixed cross-district questions on `/`, answered from published facts, no model."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.rankings import rank
from app.copy import load_copy
from app.main import app
from app.models import Fact
from app.tools.rankings import answer
from tests.regressions.test_wo97_brief_page import METHOD, VINTAGE, Node, build_db, parse, row

ROOT = Path(__file__).resolve().parents[2]
AGE = "age_65_share"
INCOME = "median_household_income"
AGE_TEXT = "Which House districts have the highest share of residents age 65 and over?"
INCOME_TEXT = "Which House districts have the lowest median household income?"

client = TestClient(app)


def house(number: int) -> str:
    return f"house:15:{number:03d}:2022"


def words() -> dict[str, str]:
    group: dict[str, str] = load_copy()["home"]["question"]
    return group


def choices(form: Node) -> list[tuple[Node, Node]]:
    return [(label, label.one("input", type="radio", name="q")) for label in form.find_all("label")]


def seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[Fact]) -> None:
    path = tmp_path / "facts.db"
    build_db(path, rows)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))


@pytest.fixture
def facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seven ranked districts for each question; District 8 has a null age value, the rest no row."""
    seed(
        tmp_path,
        monkeypatch,
        [
            row(AGE, house(1), 20.0, 1.0),
            row(AGE, house(2), 30.0, 3.0),
            row(AGE, house(3), 25.0, 2.0),
            row(AGE, house(4), 28.0, 2.0),
            row(AGE, house(5), 10.0, 9.0),  # use with caution
            row(AGE, house(6), 22.0, 1.0),
            row(AGE, house(7), 21.0, 1.0),
            row(AGE, house(8), None, None),
            row(INCOME, house(1), 90000.0, 5000.0),
            row(INCOME, house(2), 60000.0, 5000.0),
            row(INCOME, house(3), 80000.0, 5000.0),
            row(INCOME, house(4), 70000.0, 5000.0),
            row(INCOME, house(5), 100000.0, 5000.0),
            row(INCOME, house(6), 110000.0, 5000.0),
            row(INCOME, house(7), 120000.0, 5000.0),
        ],
    )


def test_rank_orders_both_ways_and_counts_what_it_leaves_out() -> None:
    facts: dict[str, Fact | None] = {
        "1": row(AGE, house(1), 10.0, 1.0),
        "2": row(AGE, house(2), 30.0, 1.0),
        "3": row(AGE, house(3), None, None),
        "4": None,
        "5": row(AGE, house(5), 20.0, 1.0),
    }
    high = rank(facts, descending=True)
    low = rank(facts, descending=False)
    assert [number for number, _ in high.ranked] == ["2", "5", "1"]
    assert [number for number, _ in low.ranked] == ["1", "5", "2"]
    assert high.left_out == low.left_out == 2


def test_rank_ties_keep_district_order() -> None:
    facts: dict[str, Fact | None] = {str(n): row(AGE, house(n), 20.0, 1.0) for n in (1, 2, 3)}
    assert [n for n, _ in rank(facts, descending=True).ranked] == ["1", "2", "3"]
    assert [n for n, _ in rank(facts, descending=False).ranked] == ["1", "2", "3"]


@pytest.mark.parametrize(
    ("second", "second_moe", "overlaps"),
    [
        (10.0, 2.0, False),  # difference 10 > 2 + 2
        (16.0, 2.0, True),  # difference 4 == 2 + 2: touching margins overlap
        (16.1, 2.0, True),
        (15.0, None, True),  # no margin to compare: treated as overlapping
    ],
)
def test_overlap_rule(second: float, second_moe: float | None, overlaps: bool) -> None:
    facts: dict[str, Fact | None] = {
        "1": row(AGE, house(1), 20.0, 2.0),
        "2": row(AGE, house(2), second, second_moe),
    }
    assert rank(facts, descending=True).overlaps is overlaps


def test_overlap_looks_only_at_the_top_five() -> None:
    values = [90.0, 80.0, 70.0, 60.0, 50.0, 49.9]
    facts: dict[str, Fact | None] = {
        str(i): row(AGE, house(i), v, 1.0) for i, v in enumerate(values, 1)
    }
    assert rank(facts, descending=True).overlaps is False


def test_control_sits_above_the_picker_and_works_both_ways(facts: None) -> None:
    html = client.get("/").text
    page = parse(html)
    form = page.one("form", class_="question")
    assert html.index('class="question"') < html.index('class="picker"')
    assert form.attrs["action"] == "/"
    assert form.attrs["method"] == "get"
    assert form.attrs["hx-get"] == "/questions"
    assert form.attrs["hx-target"] == "#question-answer"
    assert form.attrs["hx-swap"] == "innerHTML"
    assert [(i.attrs["value"], label.text) for label, i in choices(form)] == [
        (AGE, AGE_TEXT),
        (INCOME, INCOME_TEXT),
    ]
    assert [i.attrs["value"] for _, i in choices(form) if "checked" in i.attrs] == [AGE]
    assert form.one("legend").text
    assert form.one("button", type="submit").text
    assert page.one("div", id="question-answer").text == ""


def test_plain_get_answers_on_the_home_page(facts: None) -> None:
    response = client.get("/", params={"q": INCOME})
    assert response.status_code == 200
    page = parse(response.text)
    assert page.one("h1").text
    assert page.one("form", class_="picker")
    form = page.one("form", class_="question")
    assert [i.attrs["value"] for _, i in choices(form) if "checked" in i.attrs] == [INCOME]
    assert len(page.one("div", id="question-answer").find_all("li")) == 5


def test_htmx_route_returns_only_the_answer_block(facts: None) -> None:
    response = client.get("/questions", params={"q": AGE})
    assert response.status_code == 200
    assert "<html" not in response.text
    page = parse(response.text)
    assert page.find_all("form") == []
    assert len(page.find_all("li")) == 5


@pytest.mark.parametrize(
    ("q", "numbers", "text", "first"),
    [
        (AGE, [2, 4, 3, 6, 7], AGE_TEXT, "30.0%"),
        (INCOME, [2, 4, 3, 1, 5], INCOME_TEXT, "$60,000"),
    ],
)
def test_five_ranked_linked_districts_and_one_sentence(
    facts: None, q: str, numbers: list[int], text: str, first: str
) -> None:
    page = parse(client.get("/questions", params={"q": q}).text)
    assert text in page.text
    links = [li.one("a") for li in page.find_all("li")]
    assert [a.attrs["href"] for a in links] == [f"/brief/house/{n}" for n in numbers]
    assert links[0].text == f"Hawaiʻi State House District {numbers[0]}"
    finding = page.one("p", class_="question-finding").text
    assert len(re.findall(r"[.?!](\s|$)", finding)) == 1
    assert f"Hawaiʻi State House District {numbers[0]}" in finding
    assert first in finding
    assert "±" in finding


def test_every_ranked_figure_is_cited_with_its_uncertainty(facts: None) -> None:
    page = parse(client.get("/questions", params={"q": AGE}).text)
    items = page.find_all("li")
    expected = [("30.0%", "±3.0%", "reliable"), ("28.0%", "±2.0%", "reliable")]
    for li, (value, moe, word) in zip(items, expected, strict=False):
        assert li.one("data", class_="value").text == value
        assert li.one("span", class_="moe").text == moe
        assert li.one("span", class_="reliability").text == word
    for li in items:
        cited = li.one("small", class_="question-citation").text
        for part in ("synthetic test row", "DP05", VINTAGE, "Hawaiʻi State House District", METHOD):
            assert part in cited


def test_a_cautioned_district_is_shown_with_its_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(tmp_path, monkeypatch, [row(AGE, house(9), 40.0, 30.0)])
    page = parse(client.get("/questions", params={"q": AGE}).text)
    assert page.one("span", class_="reliability").text == "use with caution"


def test_overlapping_margins_are_said_in_words(facts: None) -> None:
    page = parse(client.get("/questions", params={"q": AGE}).text)
    assert words()["overlap"] in page.text
    assert words()["distinct"] not in page.text


def test_separated_margins_do_not_claim_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(tmp_path, monkeypatch, [row(AGE, house(n), n * 10.0, 1.0) for n in range(1, 7)])
    page = parse(client.get("/questions", params={"q": AGE}).text)
    assert words()["overlap"] not in page.text
    assert words()["distinct"] in page.text


def test_districts_without_a_value_are_left_out_and_the_answer_says_so(facts: None) -> None:
    page = parse(client.get("/questions", params={"q": AGE}).text)
    assert all(a.attrs["href"] != "/brief/house/8" for a in page.find_all("a"))
    assert words()["left_out"].format(count=44) in page.text


def test_nothing_left_out_says_nothing_about_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(tmp_path, monkeypatch, [row(AGE, house(n), 20.0 + n, 1.0) for n in range(1, 52)])
    page = parse(client.get("/questions", params={"q": AGE}).text)
    assert page.find_all("p", class_="question-left-out") == []


def test_no_published_values_is_an_answer_not_a_ranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(tmp_path, monkeypatch, [row(AGE, house(1), None, None)])
    page = parse(client.get("/questions", params={"q": AGE}).text)
    assert words()["no_figures"] in page.text
    assert page.find_all("ol") == []
    assert words()["overlap"] not in page.text
    assert words()["distinct"] not in page.text


@pytest.mark.parametrize("path", ["/", "/questions"])
@pytest.mark.parametrize("q", ["", "age", "AGE_65_SHARE", "population", "../etc", "x\ny"])
def test_unknown_question_is_an_error_not_a_guess(facts: None, path: str, q: str) -> None:
    response = client.get(path, params={"q": q})
    assert response.status_code == 400
    assert response.json()["detail"] == words()["unknown"].format(valid=f"{AGE}, {INCOME}")


def test_questions_route_requires_a_question(facts: None) -> None:
    assert client.get("/questions").status_code == 400


def test_tool_rejects_unknown_question_naming_the_valid_ones() -> None:
    with pytest.raises(ValueError, match=f"{AGE}, {INCOME}"):
        answer("population")


def test_all_wording_lives_in_copy() -> None:
    home = (ROOT / "templates/home.html").read_text(encoding="utf-8")
    block = home[home.index('<form class="question"') : home.index('<form class="picker"')]
    partial = (ROOT / "templates/partials/question_answer.html").read_text(encoding="utf-8")
    for template in (block, partial):
        bare = re.sub(r"{{.*?}}|{%.*?%}", "", template, flags=re.DOTALL)
        assert parse(bare).text == ""
