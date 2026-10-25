"""WO #67: complete named brackets, explicit caveats and closed nested models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.programs import Program, load_catalog

CATALOG = Path(__file__).resolve().parents[2] / "data/programs.yaml"


@pytest.mark.parametrize(
    "edge,count", [(0.5, 1), (1.0, 2), (1.25, 3), (1.5, 4), (1.85, 5), (2.0, 6)]
)
def test_proxy_accepts_only_complete_brackets(edge: float, count: int) -> None:
    entry = load_catalog(CATALOG)[0].model_dump(mode="json")
    proxy = entry["eligibility_proxy"]
    proxy["threshold"] = edge
    proxy["acs_fields"] = [f"C17002_{n:03d}E" for n in range(2, count + 2)]
    assert Program.model_validate(entry).eligibility_proxy.threshold == edge
    proxy["acs_fields"].pop(0)
    with pytest.raises(ValidationError):
        Program.model_validate(entry)


@pytest.mark.parametrize("word", ["lower bound", "understate"])
def test_each_proxy_caveat_is_required(word: str) -> None:
    entry = load_catalog(CATALOG)[0].model_dump(mode="json")
    proxy = entry["eligibility_proxy"]
    proxy["method"] = proxy["method"].replace(word, "")
    with pytest.raises(ValidationError):
        Program.model_validate(entry)


@pytest.mark.parametrize("nested", ["eligibility_proxy", "agency_guideline"])
def test_nested_models_reject_extra_keys(nested: str) -> None:
    entry = load_catalog(CATALOG)[0].model_dump(mode="json")
    entry[nested]["unexpected"] = "extra"
    with pytest.raises(ValidationError):
        Program.model_validate(entry)
