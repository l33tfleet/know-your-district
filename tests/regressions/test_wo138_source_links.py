"""Offline identity and rendered coverage for published-value checks (#138)."""

import importlib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import features, snap
from app.counties import load_mapping
from app.main import app
from app.models import Fact
from app.source_links import source_links
from tests.regressions.test_wo97_brief_page import build_db, parse, row

CELLS = [
    ("B01003_001E", "B01003", "", "ACSDT"),
    ("DP05_0024PE", "DP05", "/profile", "ACSDP"),
    ("B19013_001E", "B19013", "", "ACSDT"),
    ("B22003_006E", "B22003", "", "ACSDT"),
    ("S1701_C03_001E", "S1701", "/subject", "ACSST"),
    ("C17002_002E", "C17002", "", "ACSDT"),
]
GEOS = [
    ("house:15:001:2022", "state legislative district (lower chamber):001", "620XX00US15001"),
    ("senate:15:005:2022", "state legislative district (upper chamber):005", "610XX00US15005"),
    ("county:15:001", "county:001", "050XX00US15001"),
    ("state:15", "state:15", "040XX00US15"),
]


def fact(variable: str = "B01003_001E", geography: str = GEOS[0][0]) -> Fact:
    return row("population", geography, 100, 10).model_copy(
        update={"variable": variable, "table_id": variable.split("_")[0]}
    )


@pytest.mark.parametrize("variable,table,suffix,family", CELLS)
@pytest.mark.parametrize("geography,selection,geoid", GEOS)
@pytest.mark.parametrize("vintage,year", [("2020–2024", "2024"), ("2019–2023", "2023")])
def test_fact_identity(
    variable: str,
    table: str,
    suffix: str,
    family: str,
    geography: str,
    selection: str,
    geoid: str,
    vintage: str,
    year: str,
) -> None:
    value = fact(variable, geography).model_copy(
        update={"vintage": vintage, "endpoint": "https://api.census.gov/ignored?key=SECRET"}
    )
    links = source_links(value)
    assert [link.kind for link in links] == ["table", "api"]
    params = {"get": variable, "for": selection}
    if not geography.startswith("state:"):
        params["in"] = "state:15"
    assert (
        links[1].url == f"https://api.census.gov/data/{year}/acs/acs5{suffix}?{urlencode(params)}"
    )
    assert links[0].url == f"https://data.census.gov/table/{family}5Y{year}.{table}?g={geoid}"
    for link in links:
        parsed = urlsplit(link.url)
        assert parsed.username is None and parsed.password is None
        assert "key" not in parse_qs(parsed.query)
        assert "SECRET" not in link.url


@pytest.mark.parametrize(
    "update",
    [
        {"source": "State published report", "endpoint": "https://example.org/report.csv"},
        {"method": "apportioned by area", "endpoint": "https://example.org/mapping.tsv"},
        {
            "method": "published estimate; apportioned by area",
            "endpoint": "https://example.org/mapping.tsv",
        },
        {"method": "derived sum of cells", "endpoint": "https://example.org/cells.tsv"},
    ],
)
def test_recorded_evidence_for_nonpublished_values(update: dict[str, str]) -> None:
    value = fact().model_copy(update=update)
    links = source_links(value)
    assert [(link.kind, link.url) for link in links] == [("evidence", value.endpoint)]


@pytest.mark.parametrize(
    "update,error",
    [
        ({"table_id": "X001"}, "table identity"),
        ({"variable": "B19013_001E"}, "variable identity"),
        ({"vintage": "latest"}, "ACS vintage"),
        ({"vintage": "2021–2024"}, "ACS vintage"),
        ({"geography": "tract:15:001:000100"}, "geography"),
    ],
)
def test_invalid_published_identity_fails(update: dict[str, str], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        source_links(fact().model_copy(update=update))


@pytest.mark.parametrize(
    "endpoint",
    [
        "javascript:alert(1)",
        "https:///missing-host",
        "https://user:secret@example.org/file",
        "https://example.org/file?key=secret",
        "https://example.org/file?key=",
        "https://example.org/file\n",
    ],
)
def test_recorded_evidence_rejects_unsafe_or_credential_urls(endpoint: str) -> None:
    with pytest.raises(ValueError, match="source evidence URL"):
        source_links(fact().model_copy(update={"source": "State report", "endpoint": endpoint}))


@pytest.fixture
def policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "features.toml"
    path.write_text('outreach = "on"\nsource_links = "preview"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    mapping = load_mapping()
    original = mapping["house:15:013:2022"][0]
    mapping[original.district] = [
        original.model_copy(update={"area_share": 0.5}),
        original.model_copy(update={"county": "county:15:001", "area_share": 0.5}),
    ]
    monkeypatch.setattr(
        importlib.import_module("app.sections.20_figures"), "load_mapping", lambda: mapping
    )
    monkeypatch.setattr(snap, "load_mapping", lambda: mapping)
    geographies = [g[0] for g in GEOS] + ["county:15:009", "house:15:013:2022"]
    rows = [
        row(name, g, 100, 10)
        for name in ("population", "age_65_share", "median_household_income")
        for g in geographies
    ]
    db = tmp_path / "facts.db"
    build_db(db, rows)
    monkeypatch.setenv("KYD_FACTS_DB", str(db))
    snap_db = tmp_path / "snap.db"
    build_db(snap_db, [fact("B22003_006E", g) for g in geographies])
    monkeypatch.setattr(snap, "SNAP_DB", snap_db)
    return path


@pytest.mark.parametrize(
    "status,query,shown",
    [
        ("off", "?preview=1", False),
        ("preview", "", False),
        ("preview", "?preview=1", True),
        ("on", "", True),
    ],
)
@pytest.mark.parametrize("path", ["/brief/house/1", "/brief/senate/5", "/brief/house/13"])
def test_links_cover_every_existing_citation_and_preserve_readings(
    policy: Path,
    status: str,
    query: str,
    shown: bool,
    path: str,
) -> None:
    policy.write_text(f'outreach = "on"\nsource_links = "{status}"\n')
    response = TestClient(app).get(path + query)
    assert response.status_code == 200
    page = parse(response.text)
    citations = page.find_all(class_="citation") + page.find_all(class_="outreach-citation")
    assert len(citations) >= 12
    for citation in citations:
        links = citation.find_all("a")
        assert len(links) == (2 if shown else 0)
        if shown:
            assert links[0].attrs["href"].startswith("https://data.census.gov/table/")
            assert "may require an API key" in links[1].text
        assert "2020–2024" in citation.text
        assert "published estimate" in citation.text
    assert page.find_all(class_="value")
    assert page.find_all(class_="moe")
    assert page.find_all(class_="reliability")
    mapping = page.find_all(class_="county-mapping-source")
    assert bool(mapping) == path.endswith("/13")
    if mapping:
        urls = [a.attrs["href"] for a in mapping[0].find_all("a")]
        assert len(urls) == (3 if shown else 0)
        if shown:
            recorded = load_mapping()["house:15:013:2022"][0]
            assert urls == [
                recorded.district_source,
                recorded.county_source,
                "https://github.com/l33tfleet/know-your-district/blob/main/data/district_counties.tsv",
            ]
        assert "equal-area polygon intersection" in mapping[0].text


def test_derived_evidence_and_method_render_in_both_sections(
    policy: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    derived = fact().model_copy(
        update={
            "method": "apportioned by area; synthetic test evidence",
            "endpoint": "https://example.org/source.tsv",
        }
    )
    db = policy.parent / "derived.db"
    build_db(
        db, [derived, derived.model_copy(update={"variable": "B22003_006E", "table_id": "B22003"})]
    )
    monkeypatch.setenv("KYD_FACTS_DB", str(db))
    monkeypatch.setattr(snap, "SNAP_DB", db)
    page = parse(TestClient(app).get("/brief/house/1?preview=1").text)
    citations = page.find_all(class_="citation") + page.find_all(class_="outreach-citation")
    assert len(citations) == 2
    for citation in citations:
        assert [a.attrs["href"] for a in citation.find_all("a")] == [derived.endpoint]
        assert derived.method in citation.text


def test_missing_rows_have_no_value_links(policy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYD_FACTS_DB", str(policy.parent / "absent.db"))
    monkeypatch.setattr(snap, "SNAP_DB", policy.parent / "absent-snap.db")
    page = parse(TestClient(app).get("/brief/house/1?preview=1").text)
    assert not page.find_all(class_="citation")
    assert not page.find_all(class_="outreach-citation")
    assert "No published figure" in page.text
    assert not [a for a in page.find_all("a") if "data.census.gov" in a.attrs.get("href", "")]


def test_shipping_policy_is_not_promoted() -> None:
    assert features.validate_features()["source_links"] in ("off", "preview")
