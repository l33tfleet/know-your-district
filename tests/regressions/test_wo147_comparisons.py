"""WO204 / WO147 step 3: derived population sums and shares, and their brief section.

Sums and shares are derived outside `Fact`: each names its numerator, denominator and
universe, carries every input cell's table, vintage and geography, and uses the Census
approximations (sum: root-sum-of-squares; share: ACS handbook proportion formula, with
the ratio formula when the proportion radicand is negative). Missing inputs stay missing.
"""

import math
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import features
from app.analysis.populations import Derived, compare, share, total
from app.brief import discover
from app.main import app as asgi_app
from app.models import Fact
from app.page_state import page_state
from app.populations import Population, load_populations

DISTRICT = "house:15:022:2022"
COUNTY = "county:15:003"
STATE = "state:15"
VINTAGE = "2020–2024"


def fact(
    variable: str,
    value: float | None,
    moe: float | None,
    geography: str = DISTRICT,
    moe_annotation: str | None = None,
) -> Fact:
    if value is None:
        cv, reliability = None, "unavailable"
    elif value == 0 or moe is None:
        cv, reliability = None, "caution"
    else:
        cv = moe / 1.645 / value
        reliability = "reliable" if cv <= 0.15 else "moderate" if cv <= 0.30 else "caution"
    return Fact(
        variable=variable,
        geography=geography,
        vintage=VINTAGE,
        value=value,
        moe=moe,
        cv=cv,
        reliability=reliability,
        source="U.S. Census Bureau ACS 5-year",
        table_id=variable.split("_")[0],
        method="published estimate and 90% margin of error",
        endpoint="https://api.census.gov/data/2024/acs/acs5",
        label="Estimate!!Total",
        moe_annotation=moe_annotation,
    )


def keyed(*facts: Fact) -> dict[tuple[str, str], Fact]:
    return {(f.variable, f.geography): f for f in facts}


def population(key: str) -> Population:
    return next(p for p in load_populations().populations if p.id == key)


# --- sums -----------------------------------------------------------------------------------


def test_sum_moe_is_root_sum_of_squares_and_names_its_cells() -> None:
    facts = keyed(fact("B01001_003E", 300, 40), fact("B01001_027E", 200, 30))
    result = total(("B01001_003E", "B01001_027E"), DISTRICT, facts)
    assert result.value == 500
    assert result.moe == pytest.approx(50.0)
    assert result.cv == pytest.approx(50 / 1.645 / 500)
    assert result.reliability == "reliable"
    assert result.numerator == ("B01001_003E", "B01001_027E")
    assert result.denominator == ()
    assert result.universe == "Total population"
    assert "derived" in result.method
    assert "sqrt" in result.method


def test_controlled_moe_counts_as_zero_but_missing_moe_stays_missing() -> None:
    controlled = keyed(
        fact("B01001_001E", 1000, None, moe_annotation="*****"),
    )
    result = total(("B01001_001E",), DISTRICT, controlled)
    assert result.value == 1000
    assert result.moe == 0
    assert "controlled" in result.method

    missing = keyed(fact("B01001_003E", 300, None), fact("B01001_027E", 200, 30))
    result = total(("B01001_003E", "B01001_027E"), DISTRICT, missing)
    assert result.value == 500
    assert result.moe is None
    assert result.cv is None
    assert result.reliability == "caution"


@pytest.mark.parametrize("value", [None, "absent"])
def test_unavailable_input_makes_the_sum_unavailable(value: str | None) -> None:
    facts = keyed(fact("B01001_003E", 300, 40))
    if value is None:
        facts |= keyed(fact("B01001_027E", None, None))
    result = total(("B01001_003E", "B01001_027E"), DISTRICT, facts)
    assert result.value is None
    assert result.moe is None
    assert result.reliability == "unavailable"
    assert result.missing == ("B01001_027E",)


def test_cells_from_different_universes_are_never_summed() -> None:
    facts = keyed(fact("B11005_002E", 10, 2), fact("DP04_0141E", 10, 2))
    with pytest.raises(ValueError, match="universe"):
        total(("B11005_002E", "DP04_0141E"), DISTRICT, facts)


def test_sum_carries_every_input_cells_table_vintage_and_geography() -> None:
    facts = keyed(fact("B17001_015E", 5, 2), fact("B17001_016E", 7, 3))
    result = total(("B17001_015E", "B17001_016E"), DISTRICT, facts)
    assert [(c.variable, c.table_id, c.vintage, c.geography) for c in result.inputs] == [
        ("B17001_015E", "B17001", VINTAGE, DISTRICT),
        ("B17001_016E", "B17001", VINTAGE, DISTRICT),
    ]


# --- shares ---------------------------------------------------------------------------------


def test_joint_cell_share_uses_the_published_joint_cell_and_summed_denominator() -> None:
    """B22003_006 is a joint below-poverty/no-SNAP cell; nothing is multiplied."""
    facts = keyed(fact("B22003_003E", 60, 20), fact("B22003_006E", 40, 15))
    numerator = total(("B22003_006E",), DISTRICT, facts)
    denominator = total(("B22003_003E", "B22003_006E"), DISTRICT, facts)
    result = share(numerator, denominator)
    assert denominator.value == 100
    assert denominator.moe == pytest.approx(25.0)
    p = 0.4
    expected = math.sqrt(15**2 - p**2 * 25**2) / 100
    assert result.value == pytest.approx(40.0)
    assert result.moe == pytest.approx(expected * 100)
    assert result.cv == pytest.approx(expected / 1.645 / p)
    assert result.numerator == ("B22003_006E",)
    assert result.denominator == ("B22003_003E", "B22003_006E")
    assert result.universe == "Households"
    assert "proportion" in result.method
    assert {(c.variable, c.geography) for c in result.inputs} == {
        ("B22003_003E", DISTRICT),
        ("B22003_006E", DISTRICT),
    }


def test_share_falls_back_to_the_ratio_formula_when_the_radicand_is_negative() -> None:
    facts = keyed(fact("B11005_002E", 90, 5), fact("B11005_001E", 100, 40))
    result = share(
        total(("B11005_002E",), DISTRICT, facts), total(("B11005_001E",), DISTRICT, facts)
    )
    p = 0.9
    assert 5**2 - p**2 * 40**2 < 0
    assert result.moe == pytest.approx(math.sqrt(5**2 + p**2 * 40**2) / 100 * 100)
    assert "ratio" in result.method


def test_share_of_a_children_poverty_rate_uses_the_full_determined_status_denominator() -> None:
    entry = population("children_below_poverty")
    rows = [fact(c, 10, 3) for c in entry.denominator]
    result = compare(entry, (DISTRICT,), keyed(*rows))[0]
    assert result.count.value == 120
    assert result.share.value == pytest.approx(50.0)
    assert len(result.share.denominator) == 24
    num_moe, den_moe = math.sqrt(12 * 9), math.sqrt(24 * 9)
    expected = math.sqrt(num_moe**2 - 0.25 * den_moe**2) / 240 * 100
    assert result.share.moe == pytest.approx(expected)
    assert len(result.share.inputs) == 24


def test_shares_never_divide_cells_from_different_universes() -> None:
    """Disability (civilian noninstitutionalized) over rent burden (renter units)."""
    facts = keyed(fact("S1810_C02_001E", 50, 10), fact("DP04_0136E", 400, 30))
    with pytest.raises(ValueError, match="universe"):
        share(total(("S1810_C02_001E",), DISTRICT, facts), total(("DP04_0136E",), DISTRICT, facts))


def test_native_hawaiian_share_is_of_total_population() -> None:
    entry = population("native_hawaiian")
    facts = keyed(
        fact("B02019_002E", 250, 50), fact("B01001_001E", 1000, None, moe_annotation="*****")
    )
    result = compare(entry, (DISTRICT,), facts)[0]
    assert result.share.value == pytest.approx(25.0)
    assert result.share.universe == "Total population"
    assert result.share.moe == pytest.approx(math.sqrt(50**2 - 0) / 1000 * 100)


@pytest.mark.parametrize(
    ("rows", "missing"),
    [
        ((("B11005_002E", 5, 2),), ("B11005_001E",)),
        ((("B11005_002E", 5, 2), ("B11005_001E", None, None)), ("B11005_001E",)),
        ((), ("B11005_002E", "B11005_001E")),
    ],
)
def test_share_with_an_unavailable_input_is_unavailable_and_says_which(
    rows: tuple[tuple[str, float | None, float | None], ...], missing: tuple[str, ...]
) -> None:
    facts = keyed(*(fact(v, value, moe) for v, value, moe in rows))
    result = compare(population("households_with_children"), (DISTRICT,), facts)[0]
    assert result.share.value is None
    assert result.share.moe is None
    assert result.share.reliability == "unavailable"
    assert result.share.missing == missing


def test_zero_denominator_share_is_unavailable_not_zero() -> None:
    facts = keyed(fact("B11005_002E", 0, 10), fact("B11005_001E", 0, 10))
    result = compare(population("households_with_children"), (DISTRICT,), facts)[0]
    assert result.count.value == 0
    assert result.share.value is None
    assert result.share.reliability == "unavailable"
    assert "zero" in result.share.method


def test_share_with_missing_moe_has_no_moe_and_caution() -> None:
    facts = keyed(fact("B11005_002E", 50, None), fact("B11005_001E", 100, 10))
    result = compare(population("households_with_children"), (DISTRICT,), facts)[0]
    assert result.share.value == pytest.approx(50.0)
    assert result.share.moe is None
    assert result.share.reliability == "caution"


def test_compare_keeps_district_county_state_order_and_geography() -> None:
    entry = population("households_with_children")
    facts = keyed(
        *(
            fact(v, value, 2, geography=g)
            for g in (DISTRICT, COUNTY, STATE)
            for v, value in (("B11005_002E", 30), ("B11005_001E", 100))
        )
    )
    results = compare(entry, (DISTRICT, COUNTY, STATE), facts)
    assert [r.geography for r in results] == [DISTRICT, COUNTY, STATE]
    for r in results:
        assert {c.geography for c in r.share.inputs} == {r.geography}


def test_derived_figures_are_not_facts() -> None:
    assert not issubclass(Derived, Fact)
    assert "derived" not in Fact.model_fields


# --- brief section ---------------------------------------------------------------------------


@pytest.fixture
def populations_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    config = tmp_path / "features.toml"
    config.write_text(
        features.FEATURES_PATH.read_text(encoding="utf-8") + '\npopulations = "on"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(features, "FEATURES_PATH", config)
    yield


def fixture_db(path: Path, rows: list[Fact]) -> Path:
    columns = list(Fact.model_fields)
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"CREATE TABLE facts ({', '.join(columns)})")
        db.executemany(
            f"INSERT INTO facts VALUES ({', '.join('?' for _ in columns)})",
            [tuple(getattr(r, c) for c in columns) for r in rows],
        )
        db.commit()
    return path


def test_section_is_discovered_independently_and_off_by_default() -> None:
    state = page_state("house", "22")
    assert state is not None
    assert "populations" not in [s.name for s in discover(state)]
    assert "populations" in [s.name for s in discover()]
    html = TestClient(asgi_app).get("/brief/house/22").text
    assert 'class="populations"' not in html


@pytest.mark.usefixtures("populations_on")
def test_section_shows_unavailable_inputs_as_not_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the numerator is published: the count shows, the share names its missing denominator.
    rows = [fact("B11005_002E", 300, 40)]
    monkeypatch.setenv("KYD_FACTS_DB", str(fixture_db(tmp_path / "facts.db", rows)))
    html = TestClient(asgi_app).get("/brief/house/22").text
    assert 'class="populations"' in html
    for entry in load_populations().populations:
        assert f'data-population="{entry.id}"' in html
    start = html.index('data-population="households_with_children"')
    block = html[start : html.index("</section>", start)].split('data-population="', 2)[1]
    row = block[block.index(f'<tr data-geography="{DISTRICT}"') :]
    row = row[: row.index("</tr>")]
    assert ">300<" in row
    assert '<span class="missing">not available</span>' in row
    assert "0.0%" not in row
    assert '<dd data-field="missing"><code>B11005_001E</code></dd>' in block
    assert "qualify" not in html.casefold()
    assert "eligible for" not in html.casefold()


@pytest.mark.usefixtures("populations_on")
def test_section_shows_district_county_and_state_shares_with_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        fact(v, value, moe, geography=g)
        for g in (DISTRICT, COUNTY, STATE)
        for v, value, moe in (("B11005_002E", 300, 40), ("B11005_001E", 1000, 30))
    ]
    monkeypatch.setenv("KYD_FACTS_DB", str(fixture_db(tmp_path / "facts.db", rows)))
    html = TestClient(asgi_app).get("/brief/house/22").text
    start = html.index('data-population="households_with_children"')
    block = html[start : html.index("</div>", html.index('class="derivation"', start))]
    assert block.count("30.0%") == 3
    assert "Honolulu County" in block
    assert "State of Hawaiʻi" in block
    assert "B11005_002E" in block
    assert "B11005_001E" in block
    assert "Households" in block
    assert VINTAGE in block
    assert "reliable" in block
    assert "±" in block


# --- review round 2: geography, denominators, docs --------------------------------------------


def test_share_never_divides_sums_from_different_geographies() -> None:
    facts = keyed(fact("B11005_002E", 30, 2), fact("B11005_001E", 100, 2, geography=COUNTY))
    numerator = total(("B11005_002E",), DISTRICT, facts)
    denominator = total(("B11005_001E",), COUNTY, facts)
    assert numerator.universe == denominator.universe
    with pytest.raises(ValueError, match="one geography"):
        share(numerator, denominator)


# The denominator each subgroup share actually divides by, as the brief must name it.
SUBGROUP_DENOMINATORS = {
    "children_below_poverty": "Share of children under 18 whose poverty status is determined",
    "older_below_poverty": "Share of residents 65 and over whose poverty status is determined",
    "below_poverty_no_snap": "Share of households below poverty",
}


def share_heading(html: str, key: str) -> str:
    start = html.index(f'data-population="{key}"')
    head = html[html.index("<thead>", start) : html.index("</thead>", start)]
    return head.split('<th scope="col">')[3].split("</th>")[0].strip()


@pytest.mark.usefixtures("populations_on")
def test_share_heading_names_the_actual_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A share over a subgroup is never headed with the broader universe it sits in."""
    monkeypatch.setenv("KYD_FACTS_DB", str(fixture_db(tmp_path / "facts.db", [])))
    html = TestClient(asgi_app).get("/brief/house/22").text
    for entry in load_populations().populations:
        heading = share_heading(html, entry.id)
        if entry.id in SUBGROUP_DENOMINATORS:
            assert heading == SUBGROUP_DENOMINATORS[entry.id]
            assert heading != f"Share of {entry.universe[:1].lower()}{entry.universe[1:]}"
        else:
            # Only a single universe-total cell may be headed with the universe itself.
            assert len(entry.denominator) == 1
            assert heading == f"Share of {entry.universe[:1].lower()}{entry.universe[1:]}"


def test_docs_data_md_states_the_derived_moe_formulas() -> None:
    text = (Path(__file__).resolve().parents[2] / "docs/data.md").read_text(encoding="utf-8")
    assert "sqrt(MOE₁² + MOE₂² + …)" in text
    assert "sqrt(MOE_X² - p² · MOE_Y²) / Y" in text
    assert "sqrt(MOE_X² + p² · MOE_Y²) / Y" in text
    assert "radicand" in text
