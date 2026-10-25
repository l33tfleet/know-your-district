"""Offline generation decisions for WO72 (step 2 of WO23)."""

import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import generate_golden as generator
from scripts import independent_oracle as oracle

MANIFEST = Path("scripts/golden_sample.json")
VARIABLES = {
    "B01003_001E",
    "DP05_0024PE",
    "B19013_001E",
    "S1701_C03_001E",
    "S1701_C03_010E",
    "S2301_C04_001E",
    "B22010_002E",
    "S2201_C04_001E",
    "B19055_002E",
    "B19059_002E",
    "B25064_001E",
    "S2701_C05_001E",
    "S1810_C03_001E",
    "S1602_C04_001E",
    "B08201_002E",
    "DP04_0141PE",
    "DP04_0142PE",
    *(f"C17002_{i:03}E" for i in range(1, 9)),
}


def observation(variable: str, geography: str, code: str) -> oracle.Observation:
    # Synthetic fetched cells exercise all three flags without app/ETL helpers.
    margin = {"B01003_001E": 10.0, "DP05_0024PE": 40.0}.get(variable, 80.0)
    return oracle.Observation(
        variable,
        oracle.geography_key(geography, code),
        100.0,
        margin,
        oracle.LABELS[variable],
        None,
        None,
        "U.S. Census Bureau; " + oracle.BASE,
        variable.split("_")[0],
        "Published ACS cell; 90% MOE published",
    )


def test_complete_deterministic_sample(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text())
    assert Counter(item["geography"] for item in manifest) == {
        "state legislative district (lower chamber)": 4,
        "state legislative district (upper chamber)": 3,
        "county": 4,
        "state": 1,
    }
    output = tmp_path / "golden.json"
    with patch.object(oracle, "fetch", side_effect=observation) as fetch:
        assert generator.main(["--output", str(output)]) == 0
        assert fetch.call_count == 300
    first = output.read_bytes()
    cases = json.loads(first)
    assert len(cases) == 300
    keys = {(c["variable"], c["geography"], c["vintage"]) for c in cases}
    assert len(keys) == 300
    for geography in {c["geography"] for c in cases}:
        assert {c["variable"] for c in cases if c["geography"] == geography} == VARIABLES
    assert {c["reliability"] for c in cases} == {
        "reliable",
        "moderate: use with care",
        "use with caution",
    }
    for case in cases:
        assert case["cv"] == pytest.approx(case["moe"] / 1.645 / case["value"])
        expected = (
            "reliable"
            if case["cv"] <= 0.15
            else "moderate: use with care"
            if case["cv"] <= 0.30
            else "use with caution"
        )
        assert case["reliability"] == expected
        assert case["label"] and case["source"] and case["table_id"] and case["method"]
    reversed_manifest = tmp_path / "manifest.json"
    reversed_manifest.write_text(json.dumps(list(reversed(manifest))))
    with patch.object(oracle, "fetch", side_effect=observation):
        assert generator.main(["--manifest", str(reversed_manifest), "--output", str(output)]) == 0
    assert output.read_bytes() == first


@pytest.mark.parametrize("failure", ["label", "network", "coverage", "missing-only"])
@pytest.mark.parametrize("exists", [False, True])
def test_failure_never_publishes_partial_output(tmp_path: Path, failure: str, exists: bool) -> None:
    output = tmp_path / "golden.json"
    if exists:
        output.write_text("previous complete artifact\n")
    calls = 0

    def fetch(variable: str, geography: str, code: str) -> oracle.Observation:
        nonlocal calls
        calls += 1
        result = observation(variable, geography, code)
        if calls == 150 and failure in {"label", "network"}:
            raise oracle.OracleError(
                "Census metadata mismatch" if failure == "label" else "Census request failed"
            )
        if failure in {"coverage", "missing-only"}:
            from dataclasses import replace

            return replace(result, moe=None if failure == "missing-only" else 10.0)
        return result

    with patch.object(oracle, "fetch", side_effect=fetch):
        assert generator.main(["--output", str(output)]) == 1
    assert output.exists() == exists
    if exists:
        assert output.read_text() == "previous complete artifact\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == (["golden.json"] if exists else [])


def test_real_oracle_label_drift_aborts_before_output(tmp_path: Path) -> None:
    with patch.object(oracle, "request", return_value={"label": "wrong meaning"}):
        assert generator.main(["--output", str(tmp_path / "golden.json")]) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("defect", ["duplicate", "missing", "kalawao", "wrong-counts"])
def test_manifest_requires_exact_sample(tmp_path: Path, defect: str) -> None:
    manifest = json.loads(MANIFEST.read_text())
    if defect == "duplicate":
        manifest[0] = manifest[1]
    elif defect == "missing":
        manifest.pop()
    elif defect == "kalawao":
        next(item for item in manifest if item["geography"] == "county")["code"] = "005"
    else:
        manifest[0] = {"geography": "state legislative district (upper chamber)", "code": "025"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with patch.object(oracle, "fetch") as fetch:
        assert generator.main(["--manifest", str(path), "--output", str(tmp_path / "out")]) == 1
        fetch.assert_not_called()


def test_make_golden_exposes_generator() -> None:
    import subprocess

    result = subprocess.run(["make", "-n", "golden"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "scripts.generate_golden" in result.stdout


@pytest.mark.parametrize(
    "value,moe,cv,flag",
    [
        (100.0, 24.675, 0.15, "reliable"),
        (100.0, 49.35, 0.30, "moderate: use with care"),
        (100.0, 49.36, 49.36 / 1.645 / 100, "use with caution"),
        (0.0, 1.0, None, "use with caution"),
        (None, 1.0, None, "use with caution"),
        (100.0, None, None, "use with caution"),
    ],
)
def test_independent_cv_contract(
    value: float | None, moe: float | None, cv: float | None, flag: str
) -> None:
    actual_cv, actual_flag = generator.reliability(value, moe)
    assert actual_flag == flag
    assert actual_cv == (None if cv is None else pytest.approx(cv))


def test_unavailable_cell_is_preserved(tmp_path: Path) -> None:
    from dataclasses import replace

    def fetch(variable: str, geography: str, code: str) -> oracle.Observation:
        result = observation(variable, geography, code)
        if variable == "C17002_008E":
            return replace(result, value=None, moe=None, estimate_annotation="**")
        return result

    output = tmp_path / "golden.json"
    with patch.object(oracle, "fetch", side_effect=fetch):
        assert generator.main(["--output", str(output)]) == 0
    cases = json.loads(output.read_text())
    assert len(cases) == 300
    unavailable = [case for case in cases if case["variable"] == "C17002_008E"]
    assert len(unavailable) == 12
    assert all(
        case["value"] is None
        and case["moe"] is None
        and case["cv"] is None
        and case["estimate_annotation"] == "**"
        and case["reliability"] == "use with caution"
        for case in unavailable
    )


def test_atomic_replace_failure_preserves_artifact(tmp_path: Path) -> None:
    output = tmp_path / "golden.json"
    output.write_text("previous complete artifact\n")
    with (
        patch.object(oracle, "fetch", side_effect=observation),
        patch.object(generator.os, "replace", side_effect=OSError("cannot replace")),
    ):
        assert generator.main(["--output", str(output)]) == 1
    assert output.read_text() == "previous complete artifact\n"
    assert list(tmp_path.iterdir()) == [output]
