"""Published fact row with citation and explicit uncertainty; no derived figures."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    reliability: Literal["reliable", "moderate", "caution", "unavailable"]
    source: Text
    table_id: Text
    method: Text
    endpoint: Text
    label: Text

    @model_validator(mode="after")
    def uncertainty(self) -> Self:
        if self.value is None:
            expected = "unavailable"
        elif self.value == 0 or self.moe is None:
            expected = "caution"
        else:
            if self.cv is None:
                raise ValueError("Positive sampled estimates require a CV")
            expected = (
                "reliable" if self.cv <= 0.15 else "moderate" if self.cv <= 0.30 else "caution"
            )
        if (self.value is None or self.value == 0 or self.moe is None) and self.cv is not None:
            raise ValueError("Unavailable, zero or missing-MOE estimates have no CV")
        if self.reliability != expected:
            raise ValueError("Reliability disagrees with estimate and CV")
        return self
