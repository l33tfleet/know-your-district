"""Brief sections by convention: `app/sections/NN_name.py` + `templates/sections/NN-name.html`.

Sections are found on disk and ordered by their two-digit prefix; there is no central list.
Each module defines `context(state: PageState) -> dict[str, object]`; its template gets that
dict as `section`, its own wording group from `app/copy.yaml` as `copy`, and `state`.
"""

import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.copy import section_copy
from app.page_state import PageState

SECTIONS_DIR = Path(__file__).resolve().parent / "sections"
SECTION_FILE = re.compile(r"^(?P<order>[0-9]{2})_(?P<name>[a-z][a-z0-9_]*)\.py$")

SectionContext = Callable[[PageState], dict[str, object]]


@dataclass(frozen=True)
class Section:
    order: str
    name: str

    @property
    def module(self) -> str:
        return f"app.sections.{self.order}_{self.name}"

    @property
    def template(self) -> str:
        return f"sections/{self.order}-{self.name.replace('_', '-')}.html"


def discover() -> list[Section]:
    found = (SECTION_FILE.match(path.name) for path in SECTIONS_DIR.glob("*.py"))
    return sorted(
        (Section(m["order"], m["name"]) for m in found if m), key=lambda s: (s.order, s.name)
    )


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
