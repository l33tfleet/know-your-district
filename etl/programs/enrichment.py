"""Offline enrichment contracts; no YAML statistic is rendered by the app.

A future statistic reader must return the same Pydantic figure model as FactStore.
Media licence evidence is reviewed by maintainers, never inferred from hosting.
"""

from datetime import date
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from etl.programs import FORBIDDEN

_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True, str_min_length=1)
Number = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]


def _validate_wording(value: object) -> None:
    """Apply the catalog's wording policy throughout the enrichment input."""
    if isinstance(value, str):
        if any(ord(char) < 32 for char in value):
            raise ValueError("Enrichment text contains control characters")
        if any(phrase in " ".join(value.casefold().split()) for phrase in FORBIDDEN):
            raise ValueError("Catalog text contains forbidden wording")
    elif isinstance(value, dict):
        for key, child in cast(dict[object, object], value).items():
            _validate_wording(key)
            _validate_wording(child)
    elif isinstance(value, (list, tuple)):
        for child in cast(list[object] | tuple[object, ...], value):
            _validate_wording(child)


class Statistic(BaseModel):
    """Full cited observation, retained only for offline catalog validation."""

    model_config = _CONFIG
    label: str
    value: Number
    unit: str
    geography: str
    source: str
    source_url: HttpUrl
    table_id: str
    cell: str
    vintage: str
    method: str
    moe: Number | None = None
    uncertainty: Literal["not-published"] | None = None
    uncertainty_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def wording(cls, value: object) -> object:
        _validate_wording(value)
        return value

    @model_validator(mode="after")
    def uncertainty_evidence(self) -> Self:
        if self.moe is None:
            if self.uncertainty != "not-published" or not self.uncertainty_reason:
                raise ValueError("Missing MOE requires uncertainty: not-published and a reason")
        elif self.uncertainty is not None or self.uncertainty_reason is not None:
            raise ValueError("Published MOE cannot also have unpublished uncertainty metadata")
        return self


class Permission(BaseModel):
    model_config = _CONFIG
    record_url: HttpUrl
    date: date
    permits_reuse: Literal[True]


# Only unrestricted reuse licences are recognised. The URL must identify the
# actual licence, rather than a publisher home page or unrelated terms page.
_LICENCE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
}


class Media(BaseModel):
    model_config = _CONFIG
    url: HttpUrl
    alt: str
    credit: str
    origin: Literal["federal-employee-work", "third-party"]
    licence: Literal["CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "federal-public-domain", "permission"]
    licence_url: HttpUrl | None = None
    permission: Permission | None = None

    @model_validator(mode="before")
    @classmethod
    def wording(cls, value: object) -> object:
        _validate_wording(value)
        return value

    @model_validator(mode="after")
    def reuse_evidence(self) -> Self:
        if self.licence == "permission":
            if self.permission is None:
                raise ValueError("Explicit permission requires a dated permission record")
            if self.licence_url is not None:
                raise ValueError("Use a permission record instead of licence_url for permission")
        else:
            if self.permission is not None:
                raise ValueError("Use licence: permission for a permission record")
            if self.licence_url is None:
                raise ValueError("licence_url evidence is required for media reuse")
            if self.licence == "federal-public-domain":
                if self.origin != "federal-employee-work":
                    raise ValueError(
                        "third-party media requires its own reuse licence or permission"
                    )
            elif str(self.licence_url) != _LICENCE_URLS[self.licence]:
                raise ValueError("licence_url must identify the recognised reuse licence")
        return self


class Enrichment(BaseModel):
    model_config = _CONFIG
    stats: list[Statistic] = Field(default_factory=list[Statistic])
    media: list[Media] = Field(default_factory=list[Media])
