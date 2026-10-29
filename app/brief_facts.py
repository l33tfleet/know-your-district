"""Selection and presentation shared by the brief and district-bound fact tools."""

from collections.abc import Callable

from app.copy import Copy, geography_name
from app.counties import CountyShare, load_mapping
from app.facts import FactStore, acs_config
from app.models import Fact
from etl.boundaries import DistrictId
from etl.indicators import INDICATORS

STATE = "state:15"
FORMATS: dict[str, Callable[[float], str]] = {
    "population": lambda v: f"{v:,.0f}",
    "age_65_share": lambda v: f"{v:.1f}%",
    "median_household_income": lambda v: f"${v:,.0f}",
}


def reading(
    geography: str, fact: Fact | None, fmt: Callable[[float], str], copy: Copy
) -> dict[str, object]:
    if fact is None:
        return {
            "geography": geography,
            "found": False,
            "word": copy["reliability"]["unavailable"],
            "reliability": "unavailable",
            "value_text": copy["no_row"],
        }
    return {
        "geography": geography,
        "found": True,
        "value": fact.value,
        "value_text": fmt(fact.value) if fact.value is not None else copy["not_available"],
        "moe": fact.moe,
        "moe_text": "±" + fmt(fact.moe) if fact.moe is not None else copy["no_moe"],
        "reliability": fact.reliability,
        "word": copy["reliability"][fact.reliability],
    }


def citation(fact: Fact, fmt: Callable[[float], str], copy: Copy) -> dict[str, object]:
    return {
        "fact": fact,
        "geography_name": geography_name(fact.geography),
        "moe_text": "±" + fmt(fact.moe) if fact.moe is not None else copy["no_moe"],
        "cv_text": f"{fact.cv * 100:.1f}%" if fact.cv is not None else copy["no_cv"],
    }


class BriefFacts:
    """A detached snapshot of exactly the rows displayed for one district."""

    def __init__(self, district: DistrictId, shares: list[CountyShare] | None = None) -> None:
        self.district = district.fact_key
        self.shares = load_mapping()[self.district] if shares is None else shares
        self.counties = [share.county for share in self.shares]
        self.geographies = (self.district, *self.counties, STATE)
        self.variables = {name: INDICATORS[name].variables[0] for name in FORMATS}
        vintage, _ = acs_config()
        self.facts = FactStore.default().get(
            ((v, g) for v in self.variables.values() for g in self.geographies), vintage
        )
