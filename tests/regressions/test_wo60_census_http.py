"""WO60: endpoint routing, configured vintages, metadata gates and safe failures."""

import io
import json
import traceback
from email.message import Message
from http.client import BadStatusLine
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from etl.census import CensusClient, CensusError, load_config
from etl.indicators import INDICATORS

CONFIG = Path(__file__).resolve().parents[2] / "config.toml"


@pytest.mark.parametrize("name", INDICATORS)
def test_routes_and_fetches_both_annotations(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(CONFIG)
    group = INDICATORS[name]
    calls: list[str] = []

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout > 0
        calls.append(url)
        parts = urlsplit(url)
        base = "/data/2024/acs/acs5"
        if group.endpoint != "detailed":
            base += f"/{group.endpoint}"
        assert parts.path.startswith(base)
        if "/variables/" in parts.path:
            variable = parts.path.rsplit("/", 1)[1][:-5]
            moe = group.moe_variable(variable)
            payload: object = {
                "label": config.labels[variable].format(year=config.year),
                "attributes": f"{variable}A,{moe},{moe}A",
            }
        else:
            assert parts.path == base
            query = parse_qs(parts.query)
            assert query["for"] == ["county:*"]
            assert query["in"] == ["state:15"]
            columns = query["get"][0].split(",")
            expected = [
                v for e in group.variables for v in (e, e[:-1] + "M", e + "A", e[:-1] + "MA")
            ]
            assert columns == expected
            values = ["-666666666", "-555555555", "N", "**"] * len(group.variables)
            payload = [[*columns, "state", "county"], [*values, "15", "001"]]
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("etl.census.urlopen", respond)
    result = CensusClient(config).fetch(group, "county:*")
    assert len(calls) == len(group.variables) + 1
    assert result.vintage == "2020–2024"
    assert result.rows[0][group.variables[0]] == "-666666666"
    assert result.rows[0][group.variables[0][:-1] + "M"] == "-555555555"
    assert result.rows[0][group.variables[0] + "A"] == "N"
    assert result.rows[0][group.variables[0][:-1] + "MA"] == "**"
    assert set(result.labels) == set(group.variables)


def test_config_alone_selects_another_vintage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG.read_text()
        .replace("year = 2024", "year = 2023")
        .replace('vintage = "2020–2024"', 'vintage = "2019–2023"')
    )
    config = load_config(path)
    calls: list[str] = []

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        calls.append(url)
        assert "/2023/" in url
        if "/variables/" in url:
            return io.BytesIO(
                b'{"label":"Estimate!!Median household income in the past 12 months (in 2023 inflation-adjusted dollars)","attributes":"B19013_001EA,B19013_001M,B19013_001MA"}'
            )
        assert "in=" not in url
        return io.BytesIO(
            b'[["B19013_001E","B19013_001M","B19013_001EA","B19013_001MA","state"],["100","10",null,null,"15"]]'
        )

    monkeypatch.setattr("etl.census.urlopen", respond)
    result = CensusClient(config).fetch(INDICATORS["median_household_income"], "state:15")
    assert result.vintage == "2019–2023"
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [b'{"label":"Percent!!Under 18 years"}', b"{}"])
def test_semantic_drift_stops_before_data(payload: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        calls.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr("etl.census.urlopen", respond)
    with pytest.raises(CensusError, match=r"Label mismatch.*DP05_0024PE.*2024"):
        CensusClient(load_config(CONFIG)).fetch(INDICATORS["age_65_share"], "state:15")
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["http", "protocol", "network", "json", "shape", "columns"])
def test_errors_never_echo_keys_or_response_bodies(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "private-census-key"

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        if failure == "http":
            raise HTTPError(url, 403, secret, Message(), None)
        if failure == "protocol":
            raise BadStatusLine(secret)
        if failure == "network":
            raise URLError(url + secret)
        if failure == "json":
            return io.BytesIO(secret.encode())
        if "/variables/" in url:
            return io.BytesIO(
                b'{"label":"Estimate!!Total","attributes":"B01003_001EA,B01003_001M,B01003_001MA"}'
            )
        return io.BytesIO(
            json.dumps([[secret], [secret]] if failure == "columns" else {"error": secret}).encode()
        )

    monkeypatch.setattr("etl.census.urlopen", respond)
    with pytest.raises(CensusError) as caught:
        CensusClient(load_config(CONFIG), api_key=secret).fetch(
            INDICATORS["population"], "state:15"
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert secret not in rendered
    assert "?key=" not in rendered


@pytest.mark.parametrize("change", ["year", "vintage", "label"])
def test_incomplete_or_unsupported_config_fails_clearly(change: str, tmp_path: Path) -> None:
    text = CONFIG.read_text()
    if change == "year":
        text = text.replace("year = 2024", "year = 2099")
    elif change == "vintage":
        text = text.replace('vintage = "2020–2024"', 'vintage = "2019–2023"')
    else:
        text = text.replace('B01003_001E = "Estimate!!Total"', "")
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(CensusError, match="Invalid ACS configuration"):
        load_config(path)


def test_missing_companion_metadata_blocks_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(url: str, *, timeout: int) -> io.BytesIO:
        assert "/variables/" in url
        return io.BytesIO(b'{"label":"Estimate!!Total","attributes":"B01003_001M"}')

    monkeypatch.setattr("etl.census.urlopen", respond)
    with pytest.raises(CensusError, match="Missing MOE or annotation metadata"):
        CensusClient(load_config(CONFIG)).fetch(INDICATORS["population"], "state:15")
