"""Recorded Ask decisions and deterministic rendering; live Jev routing belongs to #184.

Callers supply detached Fact tool results for the page. Upstream decisions contain
only IDs, probabilities and references, never prose, labels, values or comparisons.
The renderer resolves (variable, geography, vintage), retaining each row's own label.
"""

import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

from app.analysis.outreach import Group, compare_facts
from app.copy import geography_name, section_copy
from app.counties import load_mapping
from app.facts import acs_config
from app.models import Fact
from app.page_state import PageState
from app.sources import Identifier, Text, VariableId, load_source
from app.tools.matches import MatchReference, resolve_matches
from etl.boundaries import DistrictId

# Each route selects a published cell, never a derived count or household intersection.
VARIABLES = {
    "population": "B01003_001E",
    "age_65_share": "DP05_0024PE",
    "median_household_income": "B19013_001E",
    "poverty_65_rate": "S1701_C03_010E",
    "older_living_alone": "B11007_003E",
    "social_security_households": "B19055_002E",
    "retirement_households": "B19059_002E",
    "below_poverty_no_snap": "B22003_006E",
}
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Geography = Annotated[
    Text,
    StringConstraints(
        pattern=r"^(?:(?:house|senate):15:[0-9]{3}:2022|county:15:[0-9]{3}|state:15)$"
    ),
]


def _target(case_id: str | None, indicator_id: str | None) -> None:
    if (case_id is None) == (indicator_id is None):
        raise ValueError("supply exactly one case_id or indicator_id")
    if case_id is not None and case_id != "snap_no_receipt":
        raise ValueError("Unknown case; valid: snap_no_receipt")
    if indicator_id is not None and indicator_id not in (*VARIABLES, "none"):
        raise ValueError(f"Unknown indicator; valid: {', '.join(VARIABLES)}, none")


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    variable: VariableId
    geography: Geography
    vintage: Text


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: Identifier | None = None
    indicator_id: Identifier | None = None
    probability: Probability

    @model_validator(mode="after")
    def target(self) -> Self:
        _target(self.case_id, self.indicator_id)
        return self


class Routed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["routed"]
    case_id: Identifier | None = None
    indicator_id: Identifier | None = None
    confidence: Probability
    alternatives: tuple[Alternative, ...] = ()
    references: tuple[Reference, ...] = ()
    match_references: tuple[MatchReference, ...] = ()

    @model_validator(mode="after")
    def target(self) -> Self:
        _target(self.case_id, self.indicator_id)
        return self


class Clarify(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["clarify"]
    reason: Literal["ambiguous", "fixed_income"] = "ambiguous"
    alternatives: Annotated[tuple[Alternative, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def distinct(self) -> Self:
        keys = [(a.case_id, a.indicator_id) for a in self.alternatives]
        if len(set(keys)) != len(keys):
            raise ValueError("clarifier options must be distinct")
        return self


class Refuse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["refuse"]
    reason: Literal["individual", "partisan", "eligibility", "unsupported", "out_of_scope"]


class Paused(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["paused"]


Answer = Annotated[Routed | Clarify | Refuse | Paused, Field(discriminator="kind")]
ANSWERS: TypeAdapter[Answer] = TypeAdapter(Answer)


def parse_answer(record: object) -> Answer:
    """Validate the local facade envelope; raw Jev API responses are not this contract."""
    return ANSWERS.validate_python(record)


def _paragraph(text: str) -> Markup:
    return Markup("<p>{}</p>").format(text)


class AnswerRenderer:
    """Bind a recorded answer to the page's district, mapped counties and pinned vintage.

    References may reorder evidence, but cannot rename it or escape the page. The
    Fact objects must be tool results, not observations supplied by the classifier.
    """

    def __init__(self, district: DistrictId, facts: Sequence[Fact]) -> None:
        self.state = PageState(district=district)
        self.geographies = (
            district.fact_key,
            *(share.county for share in load_mapping()[district.fact_key]),
            "state:15",
        )
        self.vintage, _ = acs_config()
        self.facts = {(f.variable, f.geography, f.vintage): f for f in facts}
        if len(self.facts) != len(facts):
            raise ValueError("duplicate fact identity")
        self.copy = section_copy("ask")
        self.figures = section_copy("figures")
        self.units = {
            v.id: v.unit for group in load_source().indicators for v in group.variables
        } | {"B22003_006E": "households", "B11007_003E": "households"}

    def resolve(self, reference: Reference) -> Fact:
        """Resolve an exact row identity after enforcing the page's geographic scope."""
        if reference.geography not in self.geographies:
            raise ValueError("reference outside page geographies")
        key = (reference.variable, reference.geography, reference.vintage)
        if reference.vintage != self.vintage or key not in self.facts:
            raise ValueError("unknown fact reference")
        if reference.variable not in self.units:
            raise ValueError("unsupported fact unit")
        return self.facts[key]

    def compare(self, a: Reference | Mapping[str, str], b: Reference | Mapping[str, str]) -> Group:
        """Compare the same published measure, preserving whole county income."""
        left, right = Reference.model_validate(a), Reference.model_validate(b)
        if left.variable != right.variable:
            raise ValueError("comparisons require the same variable")
        return compare_facts(self.resolve(left), self.resolve(right))

    def _reading(self, fact: Fact) -> Markup:
        unit = self.units[fact.variable]

        def fmt(value: float) -> str:
            if unit == "percent":
                return f"{value:.1f}%"
            return f"${value:,.0f}" if unit == "dollars" else f"{value:,.0f}"

        if fact.moe is None:
            moe = self.figures["no_moe"]
        elif unit == "percent":
            moe = self.copy["percentage_moe"].format(value=f"{fact.moe:.1f}")
        else:
            moe = self.copy["moe"].format(value=fmt(fact.moe))
        wording = self.copy["reading"].format(
            label=fact.label,
            geography=geography_name(fact.geography),
            value=fmt(fact.value) if fact.value is not None else self.figures["not_available"],
            moe=moe,
            reliability=self.figures["reliability"][fact.reliability],
        )
        if fact.geography != self.geographies[0]:
            scope = "context"
        else:
            scope = "estimated" if "derived" in fact.method.lower() else "published"
        html = _paragraph(self.copy["geography_labels"][scope]) + _paragraph(wording)
        html += _paragraph(self.copy["citation"].format(**fact.model_dump()))
        if fact.variable in {"B22003_006E", "B19055_002E", "B22010_002E", "S2201_C04_001E"}:
            html += _paragraph(section_copy("snap")["undercount_note"])
        return html

    def _case(self, case_id: str) -> Markup:
        # Same public card builder and template used by folders (#288).
        build = cast(
            Callable[[PageState, str], dict[str, object]],
            importlib.import_module("app.sections.15_case").case_card,
        )
        card = build(self.state, case_id)
        templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")
        return Markup(
            templates.get_template("sections/15-case.html").render(
                section=card,
                copy=section_copy("case"),
                state=self.state,
            )
        )

    def render(self, answer: Answer) -> Markup:
        """Only approved copy and resolved facts reach HTML; all row text is escaped."""
        if isinstance(answer, Refuse):
            return escape(self.copy["refusals"][answer.reason])
        if isinstance(answer, Paused):
            return escape(self.copy["paused"])
        if isinstance(answer, Clarify):
            html = _paragraph(
                self.copy["fixed_income" if answer.reason == "fixed_income" else "clarify"]
            )
            for option in sorted(answer.alternatives, key=lambda a: -a.probability)[:3]:
                label = (
                    section_copy("snap")["heading"]
                    if option.case_id
                    else self.copy["refusals"]["out_of_scope"]
                    if option.indicator_id == "none"
                    else self.copy["options"][option.indicator_id]
                )
                html += _paragraph(label)
            return html
        # Validate even references attached to none/case routes, before producing output.
        facts = [self.resolve(ref) for ref in answer.references]
        if answer.match_references:
            from app.cases import case
            from app.match_cards import to_match_card

            cards = [
                to_match_card(match)
                for match in resolve_matches(self.state.district, answer.match_references)
            ]
            sentence = (
                case(answer.case_id).claim
                if answer.case_id is not None
                else self.copy["options"].get(
                    answer.indicator_id, self.copy["refusals"]["out_of_scope"]
                )
            )
            templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")
            return Markup(
                templates.get_template("partials/ask_answer.html").render(
                    answer=_paragraph(sentence), match_cards=cards
                )
            )
        if answer.indicator_id == "none":
            return escape(self.copy["refusals"]["out_of_scope"])
        html = self._case(answer.case_id) if answer.case_id is not None else Markup("")
        if answer.case_id is not None:
            return html + Markup("").join(self._reading(f) for f in facts)
        assert answer.indicator_id is not None
        variable = VARIABLES[answer.indicator_id]
        if not answer.references:
            for geography in self.geographies:
                fact = self.facts.get((variable, geography, self.vintage))
                if fact is None:
                    html += _paragraph(
                        self.copy["unavailable"].format(
                            label=self.copy["options"][answer.indicator_id],
                            geography=geography_name(geography),
                        )
                    )
                else:
                    facts.append(
                        self.resolve(
                            Reference(
                                variable=variable,
                                geography=geography,
                                vintage=self.vintage,
                            )
                        )
                    )
        html += Markup("").join(self._reading(f) for f in facts)
        district = next(
            (f for f in facts if f.geography == self.geographies[0] and f.variable == variable),
            None,
        )
        for other in facts:
            # Whole county/state counts are context, not a per-district basis.
            if (
                self.units[variable] not in {"percent", "dollars"}
                or other.geography == self.geographies[0]
                or other.variable != variable
            ):
                continue
            group = compare_facts(district, other)
            html += _paragraph(
                self.copy["comparison"].format(
                    label=other.label,
                    district=geography_name(self.geographies[0]),
                    reference=geography_name(other.geography),
                    conclusion=self.copy["comparisons"][group],
                )
            )
        if answer.indicator_id == "age_65_share":
            html += _paragraph(self.figures["count_unavailable"])
        return html
