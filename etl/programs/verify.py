"""Observe all program URLs, including optional metadata, through the HTTP facade.

Run ``uv run python -m etl.programs.verify`` to enumerate URLs and preview checks;
add ``--save`` to atomically persist observations in data/program_checks.json.
No authentication or environment variables are required. Failed, new or changed
content requires human review. After reviewing source content, a maintainer may
manually copy its observed digest into ``reviewed``; this CLI never promotes it
or renews last_verified/checked_at/refresh_after. Unchanged bytes establish only
content equality, not current program availability or eligibility.

The version-1 JSON remains compatible with the legacy checker for legacy fields.
Extended field paths are read by this command. Roll back by restoring the prior
checks JSON; neither command changes the program catalog. Unapproved media or
application hosts are enumerated but rejected by the existing HTTP trust policy.
"""

import argparse
from collections.abc import Callable, Iterator, Sequence
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from etl.programs import Program, load_catalog
from etl.programs.links import LinkCheckError, LinkResponse, fetch_url, http_content_get
from etl.programs.revalidation import Digest, StoredUrl


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    program_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]
    field: Annotated[str, Field(pattern=r"^[a-z_]+(?:\.(?:[a-z_]+|[0-9]+))*$")]
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
    observations: list[Observation] = Field(default_factory=list[Observation])

    @property
    def needs_review(self) -> bool:
        return any(
            o.sha256 is None or self.reviewed.get(o.url) != o.sha256 for o in self.observations
        )


def iter_urls(program: Program) -> Iterator[tuple[str, str]]:
    """Enumerate every typed URL and the literal 211 URL, preserving occurrences.

    Walking validated models also covers future nested URL fields without relying
    on naming conventions or accidentally treating prose containing links as URLs.
    List indices keep multiple statistics, media and permission records distinct.
    """
    yield from _walk_urls(program, "")


def _walk_urls(value: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, HttpUrl) or path == "referral_url":
        yield path, str(value)
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            child: object = getattr(value, name)
            yield from _walk_urls(child, f"{path}.{name}" if path else name)
    elif isinstance(value, list):
        for index, child in enumerate(cast(list[object], value)):
            yield from _walk_urls(child, f"{path}.{index}")


def verify(
    programs: Sequence[Program],
    previous: CheckState,
    *,
    get: Callable[[str, float], LinkResponse] = http_content_get,
) -> CheckState:
    """Hash successful bodies; contain upstream failures without granting review.

    fetch_url owns host checks, redirects and transport failure translation;
    http_content_get owns connection lifetime and per-call latency measurement.
    """
    observations: list[Observation] = []
    for program in programs:
        for field, url in iter_urls(program):
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


def load_checks(path: Path) -> CheckState:
    """Reject missing or malformed state rather than dropping reviewed history."""
    return CheckState.model_validate_json(path.read_text(encoding="utf-8"))


def save_checks(path: Path, state: CheckState) -> None:
    """Validate and atomically save an explicit observation plan."""
    payload = state.model_dump_json(indent=2) + "\n"
    CheckState.model_validate_json(payload)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(payload)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/programs.yaml"))
    parser.add_argument("--checks", type=Path, default=Path("data/program_checks.json"))
    parser.add_argument(
        "--save", action="store_true", help="save observations, never accept review"
    )
    args = parser.parse_args(argv)
    try:
        state = verify(load_catalog(args.catalog), load_checks(args.checks))
        print(state.model_dump_json(indent=2))
        print("REVIEW required" if state.needs_review else "UNCHANGED reviewed content")
        if args.save:
            save_checks(args.checks, state)
            print(f"Saved observations to {args.checks}; reviewed baseline unchanged.")
        else:
            print("Preview only; use --save to persist observations.")
    except (OSError, ValueError) as exc:
        print(f"Content check failed: {exc}")
        return 1
    return int(state.needs_review)


if __name__ == "__main__":
    raise SystemExit(main())
