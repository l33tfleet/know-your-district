"""Feature policy for #194: declarations, operator validation and preview isolation."""

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app import features
from app.page_state import PageState, page_state


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "features.toml"
    path.write_text("")
    monkeypatch.setattr(features, "FEATURES_PATH", path)
    # Declarations are process-wide; isolate this test application's declarations.
    monkeypatch.setattr(features, "VALID_NAMES", {"outreach"})
    return path


@pytest.mark.parametrize("status", ["on", "off", "preview"])
@pytest.mark.parametrize(
    "query,preview,variant",
    [
        ("", False, None),
        ("?preview=1", True, None),
        ("?v=a&preview=1", True, "a"),
        ("?v=b&preview=1", True, "b"),
        ("?v=preview", False, "preview"),
        ("?preview=0", False, None),
    ],
)
def test_route_and_omission_policy(
    config: Path, status: str, query: str, preview: bool, variant: str | None
) -> None:
    features.register_feature("test_route")
    features.register_feature("test_part")
    config.write_text(f'test_route = "{status}"\ntest_part = "{status}"\n')
    app = FastAPI()

    def state(request: Request) -> PageState:
        result = page_state(
            "house",
            "22",
            request.query_params.get("v"),
            preview=request.query_params.get("preview") == "1",
        )
        assert result is not None
        assert result.preview is preview
        assert result.variant == variant
        return result

    @app.get("/route")
    def route(request: Request) -> str:
        features.require_feature("test_route", state(request))
        return "available"

    @app.get("/parts")
    def parts(request: Request) -> list[str]:
        return ["part"] if features.enabled("test_part", state(request)) else []

    expected = status == "on" or (status == "preview" and preview)
    with TestClient(app) as client:
        response = client.get("/route" + query)
        assert response.status_code == (200 if expected else 404)
        assert client.get("/parts" + query).json() == (["part"] if expected else [])


def test_registered_unconfigured_defaults_off(config: Path) -> None:
    features.register_feature("new_part")
    features.register_feature("new_part")  # Multiple declarations may share one flag.
    policy = features.validate_features()
    assert policy["new_part"] == "off"
    for preview in (False, True):
        state = page_state("house", "22", preview=preview)
        assert state is not None
        assert not features.enabled("new_part", state)
        with pytest.raises(HTTPException) as error:
            features.require_feature("new_part", state)
        assert error.value.status_code == 404


@pytest.mark.parametrize("operation", ["config", "enabled", "required"])
def test_unknown_name_lists_valid_names(config: Path, operation: str) -> None:
    state = page_state("house", "22")
    assert state is not None
    with pytest.raises(ValueError, match=r"outrecha.*valid.*outreach"):
        if operation == "config":
            config.write_text('outrecha = "on"\n')
            features.validate_features()
        elif operation == "enabled":
            features.enabled("outrecha", state)
        else:
            features.require_feature("outrecha", state)


@pytest.mark.parametrize("value", ['"enabled"', '"ON"', "1", "[]", "{}", "true"])
def test_invalid_status_lists_options(config: Path, value: str) -> None:
    features.register_feature("test_part")
    config.write_text(f"test_part = {value}\n")
    with pytest.raises(ValueError, match=r"test_part.*on.*off.*preview"):
        features.validate_features()


@pytest.mark.parametrize("name", ["", "../part", "part?x", "part#x", "%2e", "part\n", "Part"])
def test_invalid_declaration_name(config: Path, name: str) -> None:
    with pytest.raises(ValueError, match="feature name"):
        features.register_feature(name)


def test_invalid_toml_names_file(config: Path) -> None:
    config.write_text('outreach = "on')
    with pytest.raises(ValueError, match=r"features\.toml"):
        features.validate_features()


def test_missing_config_is_actionable(config: Path) -> None:
    config.unlink()
    with pytest.raises(ValueError, match=r"features\.toml"):
        features.validate_features()


@pytest.mark.parametrize("status,expected", [("on", True), ("off", False), ("preview", False)])
def test_status_config_keeps_existing_outreach_reader(
    config: Path, status: str, expected: bool
) -> None:
    config.write_text(f'outreach = "{status}"\n')
    assert features.load_features().outreach is expected


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
def test_existing_outreach_boolean_config(config: Path, value: str, expected: bool) -> None:
    config.write_text(f"outreach = {value}\n")
    state = page_state("house", "22")
    assert state is not None
    assert features.enabled("outreach", state) is expected


def test_preview_defaults_false_and_is_independent_of_variant() -> None:
    state = page_state("house", "22", "preview")
    assert state is not None
    assert state.preview is False
    assert page_state("house", "22", "bad variant", preview=True) is None


def test_legacy_reader_allows_other_declared_features(config: Path) -> None:
    features.register_feature("new_part")
    config.write_text('outreach = "on"\nnew_part = "preview"\n')
    assert features.load_features().outreach is True


def test_operator_edits_are_revalidated(config: Path) -> None:
    state = page_state("house", "22")
    assert state is not None
    config.write_text('outreach = "on"\n')
    assert features.enabled("outreach", state)
    config.write_text('outreach = "off"\n')
    assert not features.enabled("outreach", state)
    config.write_text('outreach = "typo"\n')
    with pytest.raises(ValueError, match=r"outreach.*on.*off.*preview"):
        features.validate_features()


def test_non_utf8_config_is_actionable(config: Path) -> None:
    config.write_bytes(b"\xff")
    with pytest.raises(ValueError, match=r"features\.toml"):
        features.validate_features()


def test_unknown_name_without_declarations_explains_registration(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(features, "VALID_NAMES", set[str]())
    config.write_text('outreach = "on"\n')
    with pytest.raises(ValueError, match="register declarations first"):
        features.validate_features()
