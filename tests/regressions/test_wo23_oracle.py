"""Offline contracts for the independent Census oracle, WO71 / WO23."""

import io
import json
import traceback
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import independent_oracle as oracle


def install(
    monkeypatch: pytest.MonkeyPatch,
    variable: str = "B19013_001E",
    *,
    geography: str = "state legislative district (lower chamber)",
    code: str = "047",
    value: str = "80000",
    moe: str = "2000",
    annotation: str | None = None,
    bad_label: bool = False,
    data: object = None,
) -> list[str]:
    urls: list[str] = []

    def respond(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout > 0
        urls.append(url)
        if "/variables/" in url:
            payload: object = {
                "label": "wrong meaning" if bad_label else oracle.LABELS[variable],
                "attributes": f"{variable[:-1]}M,{variable}A,{variable[:-1]}MA",
            }
        else:
            header = [variable, variable[:-1] + "M", variable + "A", variable[:-1] + "MA"]
            row = [value, moe, annotation, None]
            header += ["state"] if geography == "state" else ["state", geography]
            row += ["15"] if geography == "state" else ["15", code]
            payload = [header, row] if data is None else data
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(oracle, "urlopen", respond)
    return urls


def test_parent_positional_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)
    assert oracle.main(["B19013_001E", "state legislative district (lower chamber)", "047"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["value"], result["moe"], result["vintage"]) == (80000, 2000, "2020–2024")
    assert (
        result["label"]
        == "Estimate!!Median household income in the past 12 months (in 2024 inflation-adjusted dollars)"
    )
    assert result["geography"] == "house:15:047:2022"


@pytest.mark.parametrize(
    "variable,suffix",
    [
        ("B01003_001E", "acs5"),
        ("DP04_0141PE", "profile"),
        ("DP04_0142PE", "profile"),
        ("S1701_C03_010E", "subject"),
    ],
)
@pytest.mark.parametrize(
    "geo,code,key",
    [
        ("state", "15", "state:15"),
        ("county", "001", "county:15:001"),
        ("state legislative district (upper chamber)", "001", "senate:15:001:2022"),
    ],
)
def test_routing_pairing_and_keys(
    monkeypatch: pytest.MonkeyPatch, variable: str, suffix: str, geo: str, code: str, key: str
) -> None:
    urls = install(monkeypatch, variable, geography=geo, code=code)
    result = oracle.fetch(variable, geo, code)
    assert result.geography == key and result.moe == 2000
    assert urlsplit(urls[-1]).path.endswith(suffix)
    query = parse_qs(urlsplit(urls[-1]).query)
    assert query["get"] == [f"{variable},{variable[:-1]}M,{variable}A,{variable[:-1]}MA"]
    assert query.get("in") == (None if geo == "state" else ["state:15"])
    assert query["for"] == [f"{geo}:{code}"]


def test_independent_metadata_rejects_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    assert len(oracle.LABELS) == 25
    assert oracle.LABELS["C17002_002E"] == "Estimate!!Total:!!Under .50"
    assert oracle.LABELS["DP04_0141PE"].endswith("!!30.0 to 34.9 percent")
    assert oracle.LABELS["DP04_0142PE"].endswith("!!35.0 percent or more")
    install(monkeypatch, bad_label=True)
    with pytest.raises(oracle.OracleError, match="metadata"):
        oracle.fetch("B19013_001E", "state", "15")


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        [["x"]],
        [["x"], ["1"]],
        [["state", "state"], ["15", "15"]],
        [["x"], [1]],
        [["x"], ["1", "2"]],
    ],
)
def test_malformed_responses_fail(monkeypatch: pytest.MonkeyPatch, data: object) -> None:
    install(monkeypatch, data=data)
    with pytest.raises(oracle.OracleError):
        oracle.fetch("B19013_001E", "state", "15")


@pytest.mark.parametrize(
    "raw", ["-666666666", "-999999999", "-888888888", "-555555555", "-222222222"]
)
def test_annotations_are_not_numbers(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    install(monkeypatch, value=raw, moe=raw, annotation="**")
    result = oracle.fetch("B19013_001E", "state legislative district (lower chamber)", "047")
    assert result.value is None and result.moe is None
    assert result.estimate_annotation == "**"
    assert ("controlled" if raw == "-555555555" else "not available") in result.method


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "garbage", "-1"])
def test_invalid_numeric_cells_fail(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    install(monkeypatch, value=raw)
    with pytest.raises(oracle.OracleError):
        oracle.fetch("B19013_001E", "state legislative district (lower chamber)", "047")


def test_key_is_environment_only_and_failures_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "private-test-key"
    monkeypatch.setenv("CENSUS_API_KEY", secret)
    urls = install(monkeypatch, geography="state", code="15")
    oracle.fetch("B19013_001E", "state", "15")
    assert all(parse_qs(urlsplit(url).query)["key"] == [secret] for url in urls)
    output = io.StringIO()
    with (
        patch.object(oracle, "urlopen", side_effect=OSError(secret)),
        redirect_stderr(output),
        redirect_stdout(output),
    ):
        assert oracle.main(["B19013_001E", "state", "15"]) == 1
        try:
            oracle.fetch("B19013_001E", "state", "15")
        except oracle.OracleError:
            traceback.print_exc(file=output)
    assert secret not in output.getvalue()


def test_open_ended_median(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, value="250001", moe="-333333333", annotation="250,000+")
    result = oracle.fetch("B19013_001E", "state legislative district (lower chamber)", "047")
    assert result.value == 250001 and result.moe is None
    assert result.estimate_annotation == "250,000+" and "top/bottom-coded" in result.method


@pytest.mark.parametrize(
    "geography,code",
    [
        ("county", "005"),
        ("state", "06"),
        ("state legislative district (lower chamber)", "1"),
        ("state legislative district (upper chamber)", "026"),
    ],
)
def test_invalid_geographies(geography: str, code: str) -> None:
    with pytest.raises(oracle.OracleError):
        oracle.fetch("B01003_001E", geography, code)


def test_wrong_response_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        geography="state",
        code="15",
        data=[
            ["B19013_001E", "B19013_001M", "B19013_001EA", "B19013_001MA", "state"],
            ["80000", "2000", None, None, "06"],
        ],
    )
    with pytest.raises(oracle.OracleError, match="geography"):
        oracle.fetch("B19013_001E", "state", "15")
