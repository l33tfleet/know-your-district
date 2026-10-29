"""Validated operator feature switches, read afresh for each section render."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

FEATURES_PATH = Path(__file__).resolve().parents[1] / "features.toml"


class Features(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    outreach: bool


def load_features() -> Features:
    return Features.model_validate(tomllib.loads(FEATURES_PATH.read_text(encoding="utf-8")))
