"""Page wording from `app/copy.yaml`, read on each request so an edit shows on the next page."""

from pathlib import Path
from typing import Any

import yaml

COPY_PATH = Path(__file__).resolve().parent / "copy.yaml"

Copy = dict[str, Any]


def load_copy() -> Copy:
    copy: Copy = yaml.safe_load(COPY_PATH.read_text(encoding="utf-8"))
    return copy


def section_copy(name: str) -> Copy:
    """A section's own wording group; a section with no group gets none."""
    group: Copy = load_copy()["sections"].get(name, {})
    return group


def geography_name(geography: str) -> str:
    """Display name of a qualified fact key: `house:15:022:2022`, `senate:…` or `state:15`."""
    names: dict[str, str] = load_copy()["geography"]
    chamber, _, rest = geography.partition(":")
    if chamber == "county":
        counties: dict[str, str] = load_copy()["counties"]
        return counties[rest.split(":")[1]]
    number = rest.split(":")[1] if chamber in ("house", "senate") else ""
    return names[chamber].format(number=int(number) if number else "")
