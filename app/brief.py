"""Brief sections by convention: `app/sections/NN_name.py` + `templates/sections/NN-name.html`.

Sections are found on disk and ordered by their two-digit prefix; there is no central list.
Each module defines `context(state: PageState) -> dict[str, object]`; its template gets that
dict as `section`, its own wording group from `app/copy.yaml` as `copy`, and `state`.
"""

import ast
import importlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.copy import section_copy
from app.features import enabled, register_feature
from app.page_state import PageState

SECTIONS_DIR = Path(__file__).resolve().parent / "sections"
SECTION_FILE = re.compile(r"^(?P<order>[0-9]{2})_(?P<name>[a-z][a-z0-9_]*)\.py$")

SectionContext = Callable[[PageState], dict[str, object]]
TemplateRenderer = Callable[[str, dict[str, object]], str]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Section:
    order: str
    name: str
    feature: str | None = None
    print_override: bool | None = None

    @property
    def printable(self) -> bool:
        return self.print_override if self.print_override is not None else self.feature is None

    @property
    def module(self) -> str:
        return f"app.sections.{self.order}_{self.name}"

    @property
    def template(self) -> str:
        return f"sections/{self.order}-{self.name.replace('_', '-')}.html"


def _metadata(path: Path) -> tuple[str | None, bool | None]:
    """Read top-level literal declarations without executing section code."""
    values: dict[str, object] = {}
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in {"FEATURE", "PRINT"}:
                expected = str if target.id == "FEATURE" else bool
                if not isinstance(value, ast.Constant) or type(value.value) is not expected:
                    raise ValueError(f"{path}: {target.id} must be a literal {expected.__name__}")
                values[target.id] = value.value
    feature = cast(str | None, values.get("FEATURE"))
    if feature is not None:
        register_feature(feature)
    return feature, cast(bool | None, values.get("PRINT"))


def discover(state: PageState | None = None) -> list[Section]:
    """Discover declarations; with request state, omit disabled features before import.

    No state preserves the legacy entry point until route integration. Collect
    every declaration before checking policy so later filenames can declare flags.
    """
    sections: list[Section] = []
    for path in SECTIONS_DIR.glob("*.py"):
        match = SECTION_FILE.match(path.name)
        if match:
            feature, print_override = _metadata(path)
            sections.append(Section(match["order"], match["name"], feature, print_override))
    sections.sort(key=lambda section: (section.order, section.name))
    return [
        section
        for section in sections
        if state is None or section.feature is None or enabled(section.feature, state)
    ]


def render_context(section: Section, state: PageState) -> dict[str, object]:
    importlib.invalidate_caches()
    module = importlib.import_module(section.module)
    build = getattr(module, "context", None)
    if not callable(build):
        raise TypeError(f"{section.module} must define context(state)")
    return {
        "section": cast(SectionContext, build)(state),
        "copy": section_copy(section.name),
        "state": state,
    }


@dataclass(frozen=True)
class RenderedSection:
    section: Section
    html: str | None
    failed: bool = False


def render_section(
    section: Section, state: PageState, renderer: TemplateRenderer
) -> RenderedSection:
    """Contain flagged import, context and template failures in one boundary.

    The caller owns the template engine and presentation of failed sections.
    Legacy render_context deliberately keeps propagating every error.
    """
    try:
        return RenderedSection(section, renderer(section.template, render_context(section, state)))
    except Exception:
        if section.feature is None:
            raise
        logger.exception(
            "Failed to render flagged section %s (%s)", section.module, section.feature
        )
        return RenderedSection(section, None, failed=True)
