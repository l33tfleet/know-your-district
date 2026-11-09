"""Canonical match permalinks, governed by the prerequisite matching feature."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.copy import geography_name
from app.features import register_feature, require_feature
from app.folders.routes import save_context
from app.page_state import page_state
from app.populations import load_populations
from app.tools.matches import CATALOG, DistrictMatches
from etl.programs import load_catalog
from etl.programs.mappings import load_mappings
from etl.programs.rules import resolve_program_id

register_feature("matches")
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")


@router.get("/match/{chamber}/{n}/{program}/{population}", response_class=HTMLResponse)
def match_page(
    request: Request,
    chamber: str,
    n: str,
    program: str,
    population: str,
    preview: str | None = None,
) -> HTMLResponse:
    """Resolve immutable IDs; disabled matches stay hidden before any data is read."""
    if preview not in (None, "0", "1"):
        raise HTTPException(status_code=404)
    state = page_state(chamber, n, preview=preview == "1")
    if state is None:
        raise HTTPException(status_code=404)
    require_feature("matches", state)
    catalog = load_catalog(CATALOG)
    try:
        resolved = resolve_program_id(catalog, program)
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    selected_population = next(
        (p for p in load_populations().populations if p.id == population), None
    )
    if selected_population is None:
        raise HTTPException(status_code=404)
    card = None
    if resolved.status == "active":
        # The adapter imports cases; keep case loading at startup, not route registration.
        from app.match_cards import to_match_card

        mappings = tuple(
            m
            for m in load_mappings()
            if m.program_id == program
            and m.population_id == population
            and m.review_status != "rejected"
        )
        if not mappings:
            raise HTTPException(status_code=404)
        matched = DistrictMatches(state.district).get_matches(mappings)
        if not matched:
            raise HTTPException(status_code=404)
        card = to_match_card(matched[0])
    # Local import shares the site's page shell without a module import cycle.
    from app.main import page_context

    title = f"{selected_population.label} · {resolved.program.name}"
    context = (
        page_context()
        | {
            "state": state,
            "title": title,
            "geography": geography_name(state.district.fact_key),
            "card": card,
            "program": resolved.program,
            "retirement": resolved.status,
            "official": "Official program information",
            "referral": "Aloha United Way 211",
        }
        | (save_context(state, "detail") if card is not None else {})
    )
    return templates.TemplateResponse(request, "match.html", context)
