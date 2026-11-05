"""#207 / #148 step 1: required identities, optional retirement and catalog growth."""

import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from shutil import copyfile
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from etl.programs import Program, load_catalog

CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


@pytest.fixture
def entry() -> dict[str, Any]:
    return load_catalog(CATALOG)[0].model_dump(mode="json")


def test_every_specified_field_is_required(entry: dict[str, Any]) -> None:
    required = {
        "id",
        "name",
        "agency",
        "level",
        "purpose",
        "eligibility_proxy",
        "agency_guideline",
        "official_url",
        "last_verified",
        "guidance",
        "referral_url",
    }
    assert {key for key, field in Program.model_fields.items() if field.is_required()} == required
    for key in required:
        broken = deepcopy(entry)
        del broken[key]
        with pytest.raises(ValidationError):
            Program.model_validate(broken)
    for key in ("eligibility_proxy", "agency_guideline"):
        for field in entry[key]:
            broken = deepcopy(entry)
            del broken[key][field]
            with pytest.raises(ValidationError):
                Program.model_validate(broken)


@pytest.mark.parametrize("additional_entries", [1, 23])
def test_catalog_growth_preserves_offline_regressions(
    tmp_path: Path, additional_entries: int
) -> None:
    programs = load_catalog(CATALOG)
    entries = [program.model_dump(mode="json") for program in programs]
    entries.extend(
        dict(entries[0], id=f"synthetic-{index}", name=f"Synthetic catalog growth fixture {index}")
        for index in range(additional_entries)
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    catalog = data_dir / "programs.yaml"
    catalog.write_text(yaml.safe_dump(entries), encoding="utf-8")
    assert len(load_catalog(catalog)) == len(entries)

    # Run both the retained suite and replacement validation against growth.
    # The superseded exact-cardinality check makes this fail on main.
    test_dir = tmp_path / "tests" / "regressions"
    test_dir.mkdir(parents=True)
    suite = test_dir / "test_wo52_program_catalog.py"
    copyfile(Path(__file__).with_name(suite.name), suite)
    replacement = test_dir / "test_wo28_catalog_growth.py"
    copyfile(Path(__file__).with_name(replacement.name), replacement)
    required_suite = test_dir / Path(__file__).name
    copyfile(Path(__file__), required_suite)
    root = CATALOG.parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "pyproject.toml"),
            str(suite),
            f"{replacement}::test_committed_catalog_validates_offline",
            f"{required_suite}::test_every_specified_field_is_required",
            "-q",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("additional_entries", [1, 23])
def test_catalog_growth_rejects_invalid_appended_entry(
    tmp_path: Path, additional_entries: int
) -> None:
    entries = [program.model_dump(mode="json") for program in load_catalog(CATALOG)]
    entries.extend(dict(entries[0], id=f"synthetic-{index}") for index in range(additional_entries))
    # Only the missing official URL is invalid, beyond the original two entries.
    del entries[-1]["official_url"]
    catalog = tmp_path / "programs.yaml"
    catalog.write_text(yaml.safe_dump(entries), encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_catalog(catalog)
    assert [(error["loc"], error["type"]) for error in exc.value.errors()] == [
        ((len(entries) - 1, "official_url"), "missing")
    ]


def write_catalog(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "programs.yaml"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "expected_error"),
    [
        ("missing", None),
        ("duplicate", "Duplicate program ID: snap"),
        ("changed", "Immutable program ID snap missing; retain it with retired metadata"),
        ("removed", "Immutable program ID snap missing; retain it with retired metadata"),
        ("reused", "Program ID snap cannot be reused for a different identity"),
    ],
)
def test_loader_rejects_broken_identities(
    tmp_path: Path, change: str, expected_error: str | None
) -> None:
    entries = [p.model_dump(mode="json") for p in load_catalog(CATALOG)]
    if change == "missing":
        entries[0].pop("id", None)
    elif change == "duplicate":
        entries.append(dict(entries[0]))
    elif change == "changed":
        entries[0]["id"] = "renamed-snap"
    elif change == "removed":
        entries.pop(0)
    else:
        entries[0].update(name="Another program", official_url="https://example.org/other/")
    with pytest.raises(ValueError) as exc:
        load_catalog(write_catalog(tmp_path, entries))
    if expected_error is None:
        assert isinstance(exc.value, ValidationError)
        assert [(error["loc"], error["type"]) for error in exc.value.errors()] == [
            ((0, "id"), "missing")
        ]
    else:
        assert str(exc.value) == expected_error


@pytest.mark.parametrize(
    "bad_id", ["SNAP", "has space", "-snap", "snap-", "a--b", "../snap", "a?b"]
)
def test_ids_are_lowercase_slugs(entry: dict[str, Any], bad_id: str) -> None:
    entry["id"] = bad_id
    with pytest.raises(ValidationError) as exc:
        Program.model_validate(entry)
    assert [(error["loc"], error["type"]) for error in exc.value.errors()] == [
        (("id",), "string_pattern_mismatch")
    ]


def test_name_can_change_but_id_is_immutable(tmp_path: Path) -> None:
    entries = [p.model_dump(mode="json") for p in load_catalog(CATALOG)]
    entries[0]["name"] = "Updated program name"
    program = load_catalog(write_catalog(tmp_path, entries))[0]
    assert program.id == "snap"
    assert program.name == "Updated program name"
    with pytest.raises(ValidationError, match="frozen_field"):
        program.id = "replacement"


def test_retirement_preserves_resolution(tmp_path: Path) -> None:
    from etl.programs.rules import resolve_program_id

    entries = [p.model_dump(mode="json") for p in load_catalog(CATALOG)]
    assert all(p.retired is None for p in load_catalog(CATALOG))
    entries[0]["retired"] = "2026-10-01"
    programs = load_catalog(write_catalog(tmp_path, entries))
    assert programs[0].retired == date(2026, 10, 1)
    result = resolve_program_id(programs, "snap")
    assert result.program is programs[0]
    assert result.status == "no longer offered"
    assert resolve_program_id(programs, "ga").status == "active"
    with pytest.raises(ValueError, match="Unknown program ID"):
        resolve_program_id(programs, "missing")
    entries[0]["retired"] = "not a date"
    with pytest.raises(ValidationError, match="retired"):
        load_catalog(write_catalog(tmp_path, entries))
