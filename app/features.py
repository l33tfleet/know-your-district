"""Feature declarations and operator policy, independent of discovery and presentation.

Routes and page parts call register_feature at declaration/import time. After
importing declarations, startup can call validate_features to reject configuration
mistakes before serving requests. Only this module reads features.toml.

New consumers use enabled for omission or require_feature for a route's 404.
The legacy outreach reader remains until request/render integration migrates it.
"""

import re
import tomllib
from enum import StrEnum
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from app.page_state import PageState

FEATURES_PATH = Path(__file__).resolve().parents[1] / "features.toml"
VALID_NAMES: set[str] = set()
_NAME = re.compile(r"[a-z][a-z0-9_]*")


class Status(StrEnum):
    ON = "on"
    OFF = "off"
    PREVIEW = "preview"


def register_feature(name: str) -> None:
    """Declare a valid flag for a route or page part; shared declarations are OK.

    Configuration cannot register names. Register before startup validation;
    an omitted configuration entry always defaults to off, including in preview.
    """
    if _NAME.fullmatch(name) is None:
        raise ValueError(
            f"Invalid feature name {name!r}; use a lowercase letter followed by "
            "lowercase letters, digits or underscores"
        )
    VALID_NAMES.add(name)


def _require_name(name: str) -> None:
    if name not in VALID_NAMES:
        options = ", ".join(sorted(VALID_NAMES)) or "(none; register declarations first)"
        raise ValueError(f"Unknown feature {name!r}; valid names: {options}")


def _read_config() -> dict[str, object]:
    try:
        return tomllib.loads(FEATURES_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot read feature configuration {FEATURES_PATH}: {exc}") from exc


def _status(name: str, value: object) -> Status:
    # Existing outreach deployments/tests use booleans. New declarations require
    # explicit statuses; this compatibility is confined to the original flag.
    if name == "outreach" and isinstance(value, bool):
        return Status.ON if value else Status.OFF
    if isinstance(value, str):
        try:
            return Status(value)
        except ValueError:
            pass
    raise ValueError(
        f"Invalid status {value!r} for feature {name!r}; valid statuses: on, off, preview"
    )


def validate_features() -> dict[str, Status]:
    """Read and validate all TOML entries; expose this check for app startup.

    Returns a complete policy including off entries for unconfigured declarations.
    No caching: subsequent operator edits are validated on the next read.
    """
    return _validate_config(_read_config())


def _validate_config(raw: dict[str, object]) -> dict[str, Status]:
    policy = dict.fromkeys(VALID_NAMES, Status.OFF)
    for name, value in raw.items():
        _require_name(name)
        policy[name] = _status(name, value)
    return policy


def enabled(name: str, state: PageState) -> bool:
    """Whether a declared page part should be included for this request."""
    _require_name(name)
    status = validate_features()[name]
    return status == Status.ON or (status == Status.PREVIEW and state.preview)


def require_feature(name: str, state: PageState) -> None:
    """Guard a declared route, hiding disabled features with an HTTP 404."""
    if not enabled(name, state):
        raise HTTPException(status_code=404)


class Features(BaseModel):
    """Compatibility shape for the existing outreach section, without preview."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    outreach: bool


def load_features() -> Features:
    """Preserve the original strict boolean reader while accepting new statuses.

    This API still requires outreach and reports its original Pydantic errors.
    New declarations use validate_features/enabled, which default omissions off.
    """
    raw = _read_config()
    legacy = {name: value for name, value in raw.items() if name not in VALID_NAMES}
    if "outreach" in raw:
        value = raw["outreach"]
        if isinstance(value, str) and value in Status:
            value = value == Status.ON
        legacy["outreach"] = value
    result = Features.model_validate(legacy)
    _validate_config(raw)
    return result


# The existing section predates declarations. Later steps register their routes
# and page parts explicitly; filenames never add names to this registry.
register_feature("outreach")
register_feature("source_links")
