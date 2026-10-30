"""Fixed cross-district questions answered from the published fact table; no model call."""

from app.analysis.rankings import Ranking, rank
from app.brief_facts import FORMATS, citation, reading
from app.copy import Copy, geography_name
from app.facts import FactStore, acs_config
from etl.boundaries import all_districts
from etl.indicators import INDICATORS

# Question key, which is also its FORMATS and copy key: (variable, highest first).
QUESTIONS: dict[str, tuple[str, bool]] = {
    "age_65_share": (INDICATORS["age_65_share"].variables[0], True),
    "median_household_income": (INDICATORS["median_household_income"].variables[0], False),
}


def answer(question: str) -> Ranking:
    if question not in QUESTIONS:
        raise ValueError(f"question must be one of: {', '.join(QUESTIONS)}")
    variable, descending = QUESTIONS[question]
    districts = all_districts("house")
    store = FactStore.default()
    # `get` reads a missing database as no rows; here that would publish 51 unpublished districts.
    if not store.path.is_file():
        raise FileNotFoundError(f"fact table not found: {store.path}")
    facts = store.get(((variable, d.fact_key) for d in districts), acs_config()[0])
    found = {str(d.district): facts.get((variable, d.fact_key)) for d in districts}
    return rank(found, descending)


def present(question: str, ranking: Ranking, copy: Copy) -> dict[str, object]:
    """The answer as the partial shows it: every word from copy, every number from a Fact."""
    words = copy["home"]["question"]
    figures = copy["sections"]["figures"]
    fmt = FORMATS[question]
    rows: list[dict[str, object]] = []
    for number, fact in ranking.top:
        cited = citation(fact, fmt, figures)
        rows.append(
            reading(fact.geography, fact, fmt, figures)
            | {
                "href": f"/brief/house/{number}",
                "name": cited["geography_name"],
                "citation": words["citation"].format(
                    source=fact.source,
                    table_id=fact.table_id,
                    vintage=fact.vintage,
                    geography=geography_name(fact.geography),
                    method=fact.method,
                    cv=cited["cv_text"],
                ),
            }
        )
    finding = words["no_figures"]
    if rows:
        first = rows[0]
        finding = words["findings"][question].format(
            district=first["name"],
            value=first["value_text"],
            moe=first["moe_text"],
            word=first["word"],
        )
    margins = None
    if len(rows) > 1:
        margins = words["overlap"] if ranking.overlaps else words["distinct"]
    left_out = words["left_out"].format(count=ranking.left_out) if ranking.left_out else None
    return {
        "question": question,
        "text": words["options"][question],
        "finding": finding,
        "margins": margins,
        "left_out": left_out,
        "rows": rows,
    }
