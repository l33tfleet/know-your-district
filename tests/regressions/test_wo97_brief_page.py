"""WO #97: the district picker on `/` and the one-page brief at `/brief/{chamber}/{n}`.

The brief shows three figures (population, share 65+, median household income), each
with value, ±MOE, a reliability word and a keyboard-reachable `<details>` source whose
fields equal the fact-table row, with the state's figure beside it. Tests read a fixture
database built from `data/schema.sql`; every row in it is synthetic.
"""

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.reliability import FLAG_WORDS, classify
from app.main import app
from app.models import Fact

ROOT = Path(__file__).resolve().parents[2]
VINTAGE = "2020–2024"
DETAILED = "https://api.census.gov/data/2024/acs/acs5"
PROFILE = "https://api.census.gov/data/2024/acs/acs5/profile"
VARIABLES = {
    "population": ("B01003_001E", "B01003", DETAILED),
    "age_65_share": ("DP05_0024PE", "DP05", PROFILE),
    "median_household_income": ("B19013_001E", "B19013", DETAILED),
}
METHOD = "published estimate and 90% margin of error"


def row(figure: str, geography: str, value: float | None, moe: float | None) -> Fact:
    """A synthetic fact, never a published observation."""
    variable, table_id, endpoint = VARIABLES[figure]
    cv, reliability = classify(
        Decimal(repr(value)) if value is not None else None,
        Decimal(repr(moe)) if moe is not None else None,
    )
    method = METHOD
    if value is None:
        method += "; estimate not available"
    if moe is None:
        method += "; MOE controlled"
    return Fact(
        variable=variable,
        geography=geography,
        vintage=VINTAGE,
        value=value,
        moe=moe,
        cv=float(cv) if cv is not None else None,
        reliability=reliability,
        source="U.S. Census Bureau ACS 5-year (synthetic test row)",
        table_id=table_id,
        method=method,
        endpoint=endpoint,
        label=f"Synthetic label for {variable}",
    )


HOUSE_22 = "house:15:022:2022"
SENATE_5 = "senate:15:005:2022"
STATE = "state:15"
ROWS = [
    row("population", HOUSE_22, 23456.0, 1234.0),  # reliable
    row("age_65_share", HOUSE_22, 21.3, 2.1),  # reliable
    row("median_household_income", HOUSE_22, 98765.0, 30000.0),  # moderate
    row("population", SENATE_5, 47012.0, 2000.0),
    row("age_65_share", SENATE_5, 17.5, 10.0),  # use with caution
    row("median_household_income", SENATE_5, None, None),  # not available
    row("population", STATE, 1446146.0, None),  # controlled MOE: caution, no CV
    row("age_65_share", STATE, 19.8, 0.1),
    row("median_household_income", STATE, 95322.0, 612.0),
]


def build_db(path: Path, rows: list[Fact]) -> None:
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "data/schema.sql").read_text())
        columns = list(Fact.model_fields)
        db.executemany(
            f"INSERT INTO facts ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [tuple(getattr(r, c) for c in columns) for r in rows],
        )
    path.chmod(0o444)


@pytest.fixture
def facts_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "facts.db"
    build_db(path, ROWS)
    monkeypatch.setenv("KYD_FACTS_DB", str(path))
    yield path


@pytest.fixture
def client(facts_db: Path) -> TestClient:
    return TestClient(app)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list["Node"] = field(default_factory=lambda: [])
    parts: list[str] = field(default_factory=lambda: [])

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())

    def find_all(self, tag: str | None = None, **attrs: str) -> list["Node"]:
        found: list[Node] = []
        for child in self.children:
            if (tag is None or child.tag == tag) and all(
                child.attrs.get(k.rstrip("_").replace("_", "-")) == v for k, v in attrs.items()
            ):
                found.append(child)
            found.extend(child.find_all(tag, **attrs))
        return found

    def one(self, tag: str | None = None, **attrs: str) -> "Node":
        found = self.find_all(tag, **attrs)
        assert len(found) == 1, (tag, attrs, len(found))
        return found[0]


VOID = {"meta", "link", "br", "hr", "img", "input"}


class Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.root = Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        while self.stack[-1].tag != tag:
            self.stack.pop()
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        for node in self.stack:
            node.parts.append(data)


def parse(html: str) -> Node:
    tree = Tree()
    tree.feed(html)
    return tree.root


def brief(client: TestClient, path: str) -> Node:
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    return parse(response.text)


# --- picker -------------------------------------------------------------------------


def test_home_no_longer_says_coming_soon(client: TestClient) -> None:
    assert "coming soon" not in client.get("/").text.lower()


def picker_form(client: TestClient) -> Node:
    page = parse(client.get("/").text)
    forms = [f for f in page.find_all("form") if f.attrs.get("action") == "/brief"]
    assert len(forms) == 1
    return forms[0]


def test_home_picker_is_a_plain_get_form_with_chamber_and_number(client: TestClient) -> None:
    form = picker_form(client)
    assert form.attrs.get("method", "get").lower() == "get"
    chamber = form.one("select", name="chamber")
    assert [o.attrs["value"] for o in chamber.find_all("option")] == ["house", "senate"]
    number = form.one("select", name="n")
    values = [o.attrs["value"] for o in number.find_all("option")]
    # Without JavaScript one number list must reach every district in both chambers.
    assert values == [str(n) for n in range(1, 52)]
    assert form.find_all("button", type="submit")
    for select in (chamber, number):
        labels = [
            lab for lab in form.find_all("label") if lab.attrs.get("for") == select.attrs["id"]
        ]
        assert len(labels) == 1 and labels[0].text


@pytest.mark.parametrize(
    ("chamber", "number", "heading"),
    [("house", "22", "House District 22"), ("senate", "5", "Senate District 5")],
)
def test_choosing_a_district_without_javascript_opens_its_brief(
    client: TestClient, chamber: str, number: str, heading: str
) -> None:
    response = client.get(
        "/brief", params={"chamber": chamber, "n": number}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/brief/{chamber}/{number}"
    page = brief(client, response.headers["location"])
    assert heading in page.one("h1").text


def test_picker_htmx_enhancement_uses_2x_attributes(client: TestClient) -> None:
    chamber = picker_form(client).one("select", name="chamber")
    assert chamber.attrs["hx-get"] == "/picker/numbers"
    assert (
        chamber.attrs["hx-target"] == "#" + picker_form(client).one("select", name="n").attrs["id"]
    )
    assert chamber.attrs["hx-swap"] == "outerHTML"
    # htmx 4 renamed/added attributes; none may appear.
    assert not [a for a in chamber.attrs if a.startswith(("hx-action", "hx-method", "hx-status"))]


@pytest.mark.parametrize(("chamber", "count"), [("house", 51), ("senate", 25)])
def test_picker_numbers_partial_matches_the_chamber(
    client: TestClient, chamber: str, count: int
) -> None:
    response = client.get("/picker/numbers", params={"chamber": chamber, "n": "40"})
    assert response.status_code == 200
    select = parse(response.text).one("select", name="n")
    options = select.find_all("option")
    assert [o.attrs["value"] for o in options] == [str(n) for n in range(1, count + 1)]
    selected = [o.attrs["value"] for o in options if "selected" in o.attrs]
    assert selected == (["40"] if count >= 40 else ["1"])


def test_picker_numbers_rejects_unknown_chamber(client: TestClient) -> None:
    assert client.get("/picker/numbers", params={"chamber": "assembly"}).status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"chamber": "assembly", "n": "1"},  # unknown chamber
        {"chamber": "senate", "n": "26"},  # out of range for the Senate
        {"chamber": "house", "n": "2a"},  # not digits
        {"chamber": "house"},  # missing number
        {"n": "3"},  # missing chamber
    ],
)
def test_picker_redirect_rejects_bad_choice_with_html_404(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get("/brief", params=params, follow_redirects=False)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "/" in [a.attrs.get("href") for a in parse(response.text).find_all("a")]


# --- 404 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/brief/house/52",  # beyond the House
        "/brief/senate/26",  # beyond the Senate
        "/brief/house/0",
        "/brief/assembly/1",  # unknown chamber
        "/brief/house/x1",  # not digits
        "/brief/House/1",  # chambers are lower case
    ],
)
def test_bad_chamber_or_number_is_html_404_with_home_link(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    page = parse(response.text)
    assert len(page.find_all("h1")) == 1
    assert [a for a in page.find_all("a") if a.attrs.get("href") == "/" and a.text]


def test_bad_variant_is_html_404(client: TestClient) -> None:
    response = client.get("/brief/house/22", params={"v": "<script>"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


def test_good_variant_is_carried_on_the_page(client: TestClient) -> None:
    page = brief(client, "/brief/house/22?v=memo-2")
    assert page.one("body").attrs.get("data-variant") == "memo-2"


# --- the brief ---------------------------------------------------------------------


def test_brief_has_headline_and_vintage_line(client: TestClient) -> None:
    page = brief(client, "/brief/senate/5")
    assert page.one("h1").text == "Hawaiʻi State Senate District 5"
    line = page.one(class_="vintage-line").text
    assert VINTAGE in line
    assert "American Community Survey" in line
    assert "2022" in line


FORMATS: dict[str, Callable[[float], str]] = {
    "population": lambda v: f"{v:,.0f}",
    "age_65_share": lambda v: f"{v:.1f}%",
    "median_household_income": lambda v: f"${v:,.0f}",
}


def check_reading(node: Node, fact: Fact, figure: str) -> None:
    """Value, ±MOE and reliability word inside one reading equal the fact row."""
    fmt = FORMATS[figure]
    value = node.one("data", class_="value")
    moe = node.find_all(class_="moe")
    word = node.one(class_="reliability")
    if fact.value is None:
        assert value.attrs["value"] == ""
        assert value.text == "not available"
    else:
        assert float(value.attrs["value"]) == fact.value
        assert value.text == fmt(fact.value)
    assert len(moe) == 1
    if fact.moe is None:
        assert moe[0].one("data").attrs["value"] == ""
    else:
        assert float(moe[0].one("data").attrs["value"]) == fact.moe
        assert moe[0].text == "±" + fmt(fact.moe)
    assert word.text == FLAG_WORDS[fact.reliability]
    assert word.attrs["data-reliability"] == fact.reliability


def check_citation(dl: Node, fact: Fact) -> None:
    for name in ("source", "table_id", "vintage", "geography", "method"):
        assert dl.one(data_field=name).text == getattr(fact, name), name
    moe = dl.one(data_field="moe").one("data").attrs["value"]
    cv = dl.one(data_field="cv").one("data").attrs["value"]
    assert (float(moe) if moe else None) == fact.moe
    assert (float(cv) if cv else None) == fact.cv
    if fact.cv is not None:
        assert dl.one(data_field="cv").text == f"{fact.cv * 100:.1f}%"


@pytest.mark.parametrize(
    ("path", "geography"), [("/brief/house/22", HOUSE_22), ("/brief/senate/5", SENATE_5)]
)
def test_each_figure_equals_the_fixture_rows(client: TestClient, path: str, geography: str) -> None:
    page = brief(client, path)
    figures = page.find_all(class_="figure")
    assert [f.attrs["data-figure"] for f in figures] == list(VARIABLES)
    for node in figures:
        figure = node.attrs["data-figure"]
        variable = VARIABLES[figure][0]
        district = next(r for r in ROWS if r.variable == variable and r.geography == geography)
        state = next(r for r in ROWS if r.variable == variable and r.geography == STATE)
        check_reading(node.one(class_="reading", data_geography=geography), district, figure)
        check_reading(node.one(class_="reading", data_geography=STATE), state, figure)
        source = node.one("details")
        summary = source.children[0]
        assert summary.tag == "summary" and summary.text
        check_citation(source.one("dl", data_geography=geography), district)
        check_citation(source.one("dl", data_geography=STATE), state)


def test_reliability_word_is_always_shown_including_caution(client: TestClient) -> None:
    page = brief(client, "/brief/senate/5")
    words = [n.attrs["data-reliability"] for n in page.find_all(class_="reliability")]
    assert len(words) == 6
    assert {"reliable", "caution", "unavailable"} <= set(words)


def test_no_comparison_words_yet(client: TestClient) -> None:
    text = brief(client, "/brief/house/22").text.lower()
    for word in ("higher", "lower", "above", "below"):
        assert f" {word} " not in f" {text} "


def test_missing_database_shows_no_numbers(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KYD_FACTS_DB", str(tmp_path / "absent.db"))
    page = brief(client, "/brief/house/22")
    assert len(page.find_all(class_="figure")) == 3
    assert not [d for d in page.find_all("data") if d.attrs.get("value")]
    assert not (tmp_path / "absent.db").exists()


def test_fact_table_is_opened_read_only(facts_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.facts import FactStore

    connect = sqlite3.connect
    uris: list[str] = []

    def checked(database: str, *, uri: bool) -> sqlite3.Connection:
        uris.append(database)
        connection = connect(database, uri=uri)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM facts")
        return connection

    monkeypatch.setattr(sqlite3, "connect", checked)
    facts = FactStore(facts_db).get([("B01003_001E", HOUSE_22)], VINTAGE)
    assert facts[("B01003_001E", HOUSE_22)].value == 23456.0
    assert uris and all(u.endswith("?mode=ro") for u in uris)
