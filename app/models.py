"""Published fact row with citation and explicit uncertainty; no derived figures."""

from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.analysis.reliability import Reliability, flag_for_cv, flag_without_cv

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variable: Text
    geography: Text
    vintage: Text
    value: Nonnegative | None
    moe: Nonnegative | None
    cv: Nonnegative | None
    reliability: Reliability
    source: Text
    table_id: Text
    method: Text
    endpoint: Text
    label: Text
    estimate_annotation: str | None = None
    moe_annotation: str | None = None

    @model_validator(mode="after")
    def uncertainty(self) -> Self:
        value = Decimal(repr(self.value)) if self.value is not None else None
        moe = Decimal(repr(self.moe)) if self.moe is not None else None
        expected = flag_without_cv(value, moe)
        if expected is not None:
            if self.cv is not None:
                raise ValueError("Unavailable, zero or missing-MOE estimates have no CV")
        else:
            if self.cv is None:
                raise ValueError("Positive sampled estimates require a CV")
            expected = flag_for_cv(Decimal(repr(self.cv)))
        if self.reliability != expected:
            raise ValueError("Reliability disagrees with estimate and CV")
        return self
