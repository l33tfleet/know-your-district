"""#363: incomplete or incompatible evidence cannot earn stronger match claims."""

from typing import Literal, cast

import pytest

from app.analysis.matching import score_match
from app.analysis.populations import Derived, compare
from app.models import Fact
from app.populations import load_populations
from etl.programs.mappings import load_mappings

POP = next(p for p in load_populations().populations if p.id == "below_poverty_no_snap")
MAPPING = next(m for m in load_mappings() if m.population_id == POP.id)


def share(geo: str, numerator: float, vintage: str = "2020–2024") -> Derived:
    """Synthetic, reliable shares with all provenance present unless a test removes it."""
    cells = tuple(
        Fact(
            variable=cell,
            geography=geo,
            vintage=vintage,
            value=value,
            moe=2,
            cv=0.02,
            reliability="reliable",
            source="Synthetic ACS fixture",
            table_id="B22003",
            method="published",
            endpoint="https://example.org",
            label="Synthetic household estimate",
        )
        for cell, value in (("B22003_006E", numerator), ("B22003_003E", 100))
    )
    return compare(POP, [geo], {(f.variable, geo): f for f in cells})[0].share


@pytest.fixture
def district() -> Derived:
    return share("house:15:022:2022", 60)


def test_benchmark_vintage_mismatch_cannot_raise_prominence(district: Derived) -> None:
    comparable = share("state:15", 20)
    assert score_match(MAPPING, POP, district, comparable).score == 1
    result = score_match(MAPPING, POP, district, share("state:15", 20, "2019–2023"))
    assert result.score == 0.6
    assert result.band == "possible"
    assert "Higher comparable population share" not in result.reason
    assert "No comparable prominence evidence" in result.reason


def test_missing_district_cells_are_insufficient(district: Derived) -> None:
    # Keep value and inputs usable so only the missing-cell guard rejects this evidence.
    incomplete = district.model_copy(update={"missing": (POP.numerator[0],)})
    result = score_match(MAPPING, POP, incomplete)
    assert result.band == "insufficient"
    assert result.score == 0


def test_district_without_source_inputs_is_insufficient(district: Derived) -> None:
    # Keep a value and no missing-cell markers to isolate absent source provenance.
    untraceable = district.model_copy(update={"inputs": ()})
    result = score_match(MAPPING, POP, untraceable)
    assert result.band == "insufficient"
    assert result.score == 0


def test_unknown_strength_is_rejected(district: Derived) -> None:
    # Deliberately cross the typed boundary to pin runtime validation of unknown flags.
    invalid = cast(Literal["direct", "indirect"], "unknown")
    with pytest.raises(ValueError, match=r"^strength must be direct or indirect$"):
        score_match(MAPPING, POP, district, strength=invalid)


def test_population_numerator_mismatch_is_rejected(district: Derived) -> None:
    incompatible = district.model_copy(update={"numerator": ("B22003_002E",)})
    with pytest.raises(ValueError, match=r"^population share mismatch$"):
        score_match(MAPPING, POP, incompatible)


def test_population_denominator_mismatch_is_rejected(district: Derived) -> None:
    incompatible = district.model_copy(update={"denominator": ("B22003_001E",)})
    with pytest.raises(ValueError, match=r"^population share mismatch$"):
        score_match(MAPPING, POP, incompatible)


def test_population_universe_mismatch_is_rejected(district: Derived) -> None:
    incompatible = district.model_copy(update={"universe": "Total population"})
    with pytest.raises(ValueError, match=r"^population share mismatch$"):
        score_match(MAPPING, POP, incompatible)
