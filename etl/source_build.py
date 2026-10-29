"""Adapt ACS manifests and stage all sources before publishing separate artifacts.

acs.yaml keeps the baseline output directory; other *.yaml manifests publish
under their validated filename stems. Rebuild a source's three artifacts together
to roll back, using the same manifest and inputs as the previous build.
"""

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from app.sources import Identifier, SourceManifest, load_source
from etl.build import ARTIFACTS, build
from etl.census import ACSConfig, CensusClient
from etl.indicators import Indicator


def adapt_source(source: SourceManifest) -> tuple[dict[str, Indicator], ACSConfig]:
    """Construct the existing Census facade inputs from one validated manifest."""
    indicators = {
        group.id: Indicator(tuple(variable.id for variable in group.variables), group.endpoint)
        for group in source.indicators
    }
    year = int(urlsplit(source.url).path.split("/")[2])
    return indicators, ACSConfig(
        year=year,
        vintage=source.vintage,
        base_url=source.url,
        state=source.geography.state,
        vintages={str(year): source.vintage},
        labels={v.id: v.expected_label for group in source.indicators for v in group.variables},
    )


def discover_sources(directory: Path) -> list[tuple[Path, SourceManifest]]:
    """Explicit discovery; require the baseline, validate every additional manifest."""
    sources = [(Path("."), load_source(directory / "acs.yaml"))]
    for path in sorted(directory.glob("*.yaml")):
        if path.name != "acs.yaml":
            name = TypeAdapter(Identifier).validate_python(path.stem)
            sources.append((Path(name), load_source(path)))
    return sources


def build_sources(directory: Path, output: Path) -> int:
    """Keep every published source intact if any fetch or validation fails."""
    sources = discover_sources(directory)
    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output.parent) as temporary:
        staged = Path(temporary)
        for relative, source in sources:
            indicators, config = adapt_source(source)
            client = CensusClient(config, api_key=os.environ.get("CENSUS_API_KEY"))
            selected = tuple(indicators[group.id] for group in source.indicators if group.build)
            count += build(client, staged / relative, indicators=selected)
        # All sources have passed schema, Fact, canonical export and digest checks.
        for relative, _source in sources:
            destination = output / relative
            destination.mkdir(parents=True, exist_ok=True)
            for name in ARTIFACTS:
                (staged / relative / name).replace(destination / name)
    return count
