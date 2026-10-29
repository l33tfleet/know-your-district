"""SNAP joint-cell results for later brief/chat consumers; no eligibility arithmetic.

Only B22003_006E is read, from the isolated read-only store. County observations
remain whole published counties, never apportioned using boundary area shares.
"""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, HttpUrl

from app.copy import geography_name, section_copy
from app.counties import load_mapping
from app.facts import FactStore, acs_config
from app.models import Fact
from etl.boundaries import DistrictId

ROOT = Path(__file__).resolve().parents[1]
SNAP_DB = ROOT / "data/snap/facts.db"
REFERRALS_PATH = ROOT / "data/snap/referrals.json"
VARIABLE = "B22003_006E"
STATE = "state:15"


class Assistance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    phone: str
    service_area: str
    service: str
    evidence: str


class Referral(BaseModel):
    """Dated contacts and their limits; income rules are not eligibility results."""

    model_config = ConfigDict(frozen=True)

    verified_on: date
    official_url: HttpUrl
    outreach_url: HttpUrl
    fallback_url: HttpUrl
    notice: str
    outreach_effective_on: date
    assistance: tuple[Assistance, ...]
    service_area_limit: str
    verification_note: str


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    geography: str
    geography_name: str
    fact: Fact | None
    units: str
    value_text: str
    moe_text: str
    reliability_word: str


class SnapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    heading: str
    period: str
    measure_note: str
    undercount_note: str
    poverty_note: str
    referral_note: str
    official_url: str
    referral_url: str
    district: Reading
    counties: tuple[Reading, ...]
    state: Reading
    referral: Referral | None


def load_result(district: DistrictId) -> SnapResult:
    """Load the validated district, every mapped county and state in one closed read.

    Missing rows retain their geography with explicit unavailable wording. The
    original Fact carries estimate, MOE, CV, reliability and the full citation.
    Missing referral artifacts retain the official DHS and 211 fallback links.
    """
    copy = section_copy("snap")
    figures = section_copy("figures")
    period, _ = acs_config()
    counties = [share.county for share in load_mapping()[district.fact_key]]
    geographies = [district.fact_key, *counties, STATE]
    facts = FactStore(SNAP_DB).get(((VARIABLE, g) for g in geographies), period)

    def reading(geography: str) -> Reading:
        fact = facts.get((VARIABLE, geography))
        return Reading(
            geography=geography,
            geography_name=geography_name(geography),
            fact=fact,
            units=copy["units"],
            value_text=f"{fact.value:,.0f}"
            if fact is not None and fact.value is not None
            else figures["not_available"],
            moe_text=f"±{fact.moe:,.0f}"
            if fact is not None and fact.moe is not None
            else figures["no_moe"],
            reliability_word=figures["reliability"][fact.reliability if fact else "unavailable"],
        )

    try:
        referral = Referral.model_validate_json(REFERRALS_PATH.read_bytes())
    except FileNotFoundError:
        referral = None
    return SnapResult(
        heading=copy["heading"],
        period=period,
        measure_note=copy["measure_note"],
        undercount_note=copy["undercount_note"],
        poverty_note=copy["poverty_note"],
        referral_note=copy["referral_note"],
        official_url=copy["official_url"],
        referral_url=copy["referral_url"],
        district=reading(district.fact_key),
        counties=tuple(reading(g) for g in counties),
        state=reading(STATE),
        referral=referral,
    )
