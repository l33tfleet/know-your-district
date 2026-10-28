"""WO #97 review round 2: a section module whose `context` is missing or not
callable fails with a clear TypeError. Each case writes its own module name and
drops it from `sys.modules` afterwards, so no case can see another case's module."""

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.brief import Section, render_context
from app.page_state import PageState
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[2]

CASES = {
    "absent": ("wo97_ctx_absent", "MARKER = 1\n"),
    "not_callable": ("wo97_ctx_not_callable", 'context = "not callable"\n'),
}


@pytest.fixture
def broken_section(request: pytest.FixtureRequest) -> Iterator[tuple[str, Section]]:
    case: str = request.param
    name, body = CASES[case]
    section = Section("16", name)
    path = ROOT / f"app/sections/16_{name}.py"
    assert not path.exists()
    assert section.module not in sys.modules
    path.write_text(f'"""Broken section added by a WO97 test."""\n\n{body}')
    try:
        yield case, section
    finally:
        path.unlink()
        sys.modules.pop(section.module, None)
        importlib.invalidate_caches()


@pytest.mark.parametrize("broken_section", list(CASES), indirect=True)
def test_section_without_callable_context_raises_type_error(
    broken_section: tuple[str, Section],
) -> None:
    case, section = broken_section
    state = PageState(district=DistrictId(chamber="house", district=22))
    with pytest.raises(TypeError) as raised:
        render_context(section, state)
    assert str(raised.value) == f"{section.module} must define context(state)"
    # The module that was imported is this case's, not a leftover from another case.
    module = sys.modules[section.module]
    if case == "absent":
        assert not hasattr(module, "context")
        assert module.MARKER == 1
    else:
        assert module.context == "not callable"
