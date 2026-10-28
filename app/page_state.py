"""What a brief page is about: the district, and an optional `?v=` page variant.

Validated once at the route; sections trust it.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from etl.boundaries import DistrictId

Variant = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,32}$")]


class PageState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district: DistrictId
    variant: Variant | None = None


def page_state(chamber: str, number: str, variant: str | None = None) -> PageState | None:
    """Return the state for a request, or None when the chamber, number or variant is invalid."""
    try:
        district = DistrictId(chamber=chamber, district=number)  # pyright: ignore[reportArgumentType] -- chamber is untrusted text; DistrictId's Literal check rejects it
        return PageState(district=district, variant=variant)
    except ValidationError:
        return None
