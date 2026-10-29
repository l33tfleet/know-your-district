"""Request-aware section discovery and isolated rendering for #195."""

import importlib
from pathlib import Path
from types import ModuleType

import pytest

from app import brief, features
from app.page_state import PageState, page_state


@pytest.fixture
def sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "sections"
    directory.mkdir()
    monkeypatch.setattr(brief, "SECTIONS_DIR", directory)
    monkeypatch.setattr(features, "VALID_NAMES", set[str]())
    policy = tmp_path / "features.toml"
    policy.write_text('experiment = "preview"\n')
    monkeypatch.setattr(features, "FEATURES_PATH", policy)
    return directory


def state(preview: bool = False) -> PageState:
    result = page_state("house", "22", preview=preview)
    assert result is not None
    return result


def test_visibility_order_and_disabled_modules_never_execute(sections: Path) -> None:
    (sections / "30_preview.py").write_text(
        'FEATURE: str = "experiment"\nraise RuntimeError("must not import")\n'
    )
    (sections / "20_core.py").write_text('raise RuntimeError("must not import")\n')
    (sections / "10_first.py").write_text("PRINT = False\n")
    (sections / "helper.py").write_text('raise RuntimeError("not a section")\n')
    assert [s.name for s in brief.discover(state())] == ["first", "core"]
    preview = brief.discover(state(True))
    assert [s.name for s in preview] == ["first", "core", "preview"]
    assert [(s.feature, s.printable) for s in preview] == [
        (None, False),
        (None, True),
        ("experiment", False),
    ]
    # The original entry point still returns all sections for the unintegrated route.
    assert [s.name for s in brief.discover()] == ["first", "core", "preview"]


@pytest.mark.parametrize("status,visible", [('"on"', True), ('"off"', False), (None, False)])
def test_on_off_and_missing_policy(sections: Path, status: str | None, visible: bool) -> None:
    (sections / "10_part.py").write_text('FEATURE = "experiment"\nPRINT = True\n')
    features.FEATURES_PATH.write_text(f"experiment = {status}\n" if status else "")
    for preview in (False, True):
        found = brief.discover(state(preview))
        assert bool(found) is visible
        if found:
            assert found[0].printable


@pytest.mark.parametrize(
    "declaration,field",
    [
        ('FEATURE = str("experiment")', "FEATURE"),
        ("FEATURE = 1", "FEATURE"),
        ("PRINT = bool(1)", "PRINT"),
        ('PRINT = "false"', "PRINT"),
    ],
)
def test_metadata_requires_literals(sections: Path, declaration: str, field: str) -> None:
    (sections / "10_part.py").write_text(declaration + "\n")
    with pytest.raises(ValueError, match=field):
        brief.discover(state())


def renderer(template: str, context: dict[str, object]) -> str:
    assert template == "sections/10-part.html"
    assert context["section"] == {"marker": "ready"}
    assert context["copy"] == {"heading": "Part"}
    assert isinstance(context["state"], PageState)
    return "<section>ready</section>"


@pytest.mark.parametrize("flagged", [False, True])
@pytest.mark.parametrize("failure", [None, "import", "context", "template", "missing_context"])
def test_rendering_contains_only_flagged_failures(
    sections: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    flagged: bool,
    failure: str | None,
) -> None:
    (sections / "10_part.py").write_text('FEATURE = "experiment"\n' if flagged else "")
    section = brief.discover()[0]
    module = ModuleType(section.module)
    error = RuntimeError(f"broken {failure}")

    def context(_state: PageState) -> dict[str, object]:
        if failure == "context":
            raise error
        return {"marker": "ready"}

    if failure != "missing_context":
        module.__dict__["context"] = context

    def load(name: str) -> ModuleType:
        assert name == section.module
        if failure == "import":
            raise error
        return module

    def render(template: str, values: dict[str, object]) -> str:
        if failure == "template":
            raise error
        return renderer(template, values)

    def copy(_name: str) -> dict[str, object]:
        return {"heading": "Part"}

    monkeypatch.setattr(importlib, "import_module", load)
    monkeypatch.setattr(brief, "section_copy", copy)
    if failure and not flagged:
        with pytest.raises(TypeError if failure == "missing_context" else RuntimeError) as raised:
            brief.render_section(section, state(True), render)
        if failure != "missing_context":
            assert raised.value is error
        assert not caplog.records
    else:
        result = brief.render_section(section, state(True), render)
        assert result.section == section
        assert result.failed is bool(failure)
        assert result.html == (None if failure else "<section>ready</section>")
        if failure:
            assert section.module in caplog.text
            assert caplog.records[-1].exc_info is not None
        else:
            assert not caplog.records


def test_legacy_context_still_propagates_flagged_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_name: str) -> ModuleType:
        raise RuntimeError("legacy error")

    monkeypatch.setattr(importlib, "import_module", broken)
    with pytest.raises(RuntimeError, match="legacy error"):
        brief.render_context(brief.Section("10", "part", feature="experiment"), state())
