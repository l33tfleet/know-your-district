"""Human-authored source contracts for ETL and rendering; no observations or I/O at import."""

from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from yaml.nodes import MappingNode, Node, SequenceNode

SOURCE_PATH = Path(__file__).resolve().parents[1] / "data/sources/acs.yaml"


def _text(value: object) -> object:
    if isinstance(value, str) and any(ord(char) < 32 for char in value):
        raise ValueError("control characters are unsupported")
    return value.strip() if isinstance(value, str) else value


Text = Annotated[
    str, BeforeValidator(_text), StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]
Identifier = Annotated[Text, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
VariableId = Annotated[
    Text,
    StringConstraints(
        pattern=r"^(?:[BC][0-9]{5}_[0-9]{3}E|DP[0-9]{2}_[0-9]{4}PE|S[0-9]{4}_C[0-9]{2}_[0-9]{3}E)$"
    ),
]


class VariableDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: VariableId
    expected_label: Text
    display_name: Text
    unit: Literal["people", "households", "percent", "dollars"]

    @model_validator(mode="after")
    def percent_unit(self) -> Self:
        if self.id.endswith("PE") and self.unit != "percent":
            raise ValueError("Published PE cells require percent unit")
        return self


class IndicatorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    endpoint: Literal["detailed", "profile", "subject"]
    build: Annotated[bool, Field(strict=True)]
    variables: Annotated[tuple[VariableDefinition, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def endpoint_contract(self) -> Self:
        if len({v.id.split("_")[0] for v in self.variables}) != 1:
            raise ValueError("Each indicator must use one table")
        for variable in self.variables:
            expected = (
                "profile"
                if variable.id.startswith("DP")
                else "subject"
                if variable.id.startswith("S")
                else "detailed"
            )
            if self.endpoint != expected:
                raise ValueError("endpoint disagrees with variable contract")
        return self


class Geography(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["15"]
    district_plan: Literal[2022]
    county_codes: tuple[Literal["001"], Literal["003"], Literal["007"], Literal["009"]]


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Text
    url: Literal["https://api.census.gov/data/2024/acs/acs5"]
    licence: Text
    geography: Geography
    vintage: Literal["2020–2024"]
    method: Literal["published estimate and 90% margin of error"]
    indicators: Annotated[tuple[IndicatorDefinition, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_definitions(self) -> Self:
        groups: set[str] = set()
        variables: set[str] = set()
        for group in self.indicators:
            if group.id in groups:
                raise ValueError(f"duplicate group: {group.id}")
            groups.add(group.id)
            for variable in group.variables:
                if variable.id in variables:
                    raise ValueError(f"duplicate variable: {variable.id}")
                variables.add(variable.id)
        return self


def _unique_keys(node: Node, seen: set[int]) -> None:
    """Check before safe_load can silently overwrite human-authored mapping keys."""
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if key.value in keys:
                raise ValueError(f"duplicate YAML key: {key.value}")
            keys.add(key.value)
            _unique_keys(value, seen)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _unique_keys(child, seen)


def load_source(path: Path = SOURCE_PATH) -> SourceManifest:
    """Read and validate one manifest, independently of the working directory."""
    content = path.read_text(encoding="utf-8")
    loader = yaml.SafeLoader(content)
    try:
        node = loader.get_single_node()
    finally:
        # PyYAML disposal returns None, but its upstream annotation is missing.
        loader.dispose()  # pyright: ignore[reportUnknownMemberType]
    if node is not None:
        _unique_keys(node, set())
    return SourceManifest.model_validate(yaml.safe_load(content))
