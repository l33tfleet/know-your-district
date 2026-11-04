"""Content observations never grant review or change catalog verification dates.

Operators preview with ``python -m etl.programs --revalidate`` and explicitly save
observations with ``--save``. After reviewing a source, an operator may copy its
observed SHA-256 into ``reviewed`` in the checks JSON; saving observations never
promotes that baseline. Empty reviewed data intentionally requires initial review.
To roll back, restore the previous checks JSON; catalog data is never modified.
No authentication or environment variables are required.
"""

from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    model_validator,
)

from etl.programs import Program
from etl.programs.links import (
    LinkCheckError,
    LinkResponse,
    UrlField,
    fetch_url,
    http_content_get,
    iter_program_urls,
)

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _valid_url(value: str) -> str:
    # Validate shape without normalization: baseline keys must round-trip exactly.
    # Trust is checked at request time so rejected catalog hosts can be reported.
    if any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("URL contains control or space")
    TypeAdapter(HttpUrl).validate_python(value)
    return value


StoredUrl = Annotated[str, AfterValidator(_valid_url)]


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    program_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]
    field: UrlField
    url: StoredUrl
    sha256: Digest | None = None
    error: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def success_or_error(self) -> Self:
        if (self.sha256 is None) == (self.error is None):
            raise ValueError("An observation requires either a SHA-256 or an error, exclusively")
        return self


class CheckState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    reviewed: dict[StoredUrl, Digest] = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=lambda: list[Observation]())

    @property
    def needs_review(self) -> bool:
        return any(
            o.sha256 is None or self.reviewed.get(o.url) != o.sha256 for o in self.observations
        )


def load_checks(path: Path) -> CheckState:
    """Fail on missing or malformed baselines rather than quietly losing review history."""
    return CheckState.model_validate_json(path.read_text(encoding="utf-8"))


def save_checks(path: Path, state: CheckState) -> None:
    """Persist only explicit plans; validate before an atomic replacement."""
    payload = state.model_dump_json(indent=2) + "\n"
    CheckState.model_validate_json(payload)
    # A same-directory temporary file keeps replacement atomic and preserves a good
    # baseline if writing fails. The operator controls the destination, not the catalog.
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(payload)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def revalidate(
    programs: Sequence[Program],
    previous: CheckState,
    *,
    get: Callable[[str, float], LinkResponse] = http_content_get,
) -> CheckState:
    """Observe every catalog URL; preserve the separately reviewed baseline verbatim."""
    observations: list[Observation] = []
    for program in programs:
        for field, url in iter_program_urls(program):
            digest: str | None = None
            error: str | None = None
            try:
                response = fetch_url(url, get=get)
                if response.status != 200:
                    error = f"HTTP {response.status}: refused automated access; not verified"
                elif response.body is None:
                    error = "Missing response body; not verified"
                else:
                    digest = sha256(response.body).hexdigest()
            except LinkCheckError as exc:
                error = str(exc)
            observations.append(
                Observation(program_id=program.id, field=field, url=url, sha256=digest, error=error)
            )
    return CheckState(reviewed=previous.reviewed.copy(), observations=observations)
