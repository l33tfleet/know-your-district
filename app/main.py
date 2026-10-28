"""ASGI entry point: `uvicorn app.main:app`."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.brief import discover, render_context
from app.copy import geography_name, load_copy
from app.page_state import page_state
from etl.boundaries import DISTRICT_COUNTS

ROOT = Path(__file__).resolve().parent.parent
HTMX_VERSION = "2.0.11"
SITE_URL = "https://district.hawaiitechmentors.org"

app = FastAPI(title="Know Your District", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def page_context() -> dict[str, object]:
    return {
        "htmx_src": f"/static/vendor/htmx-{HTMX_VERSION}.min.js",
        "site_url": SITE_URL,
        "copy": load_copy(),
    }


@app.exception_handler(404)
def not_found(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    """Unknown paths, and any route raising HTTPException(404), get an HTML page, not JSON."""
    return templates.TemplateResponse(request, "not_found.html", page_context(), status_code=404)


class Health(BaseModel):
    status: str


@app.get("/healthz")
def healthz() -> Health:
    return Health(status="ok")


def district_numbers(chamber: str, n: str | None) -> dict[str, object]:
    numbers = list(range(1, DISTRICT_COUNTS["senate" if chamber == "senate" else "house"] + 1))
    selected = int(n) if n is not None and n.isdecimal() and int(n) in numbers else 1
    return {"numbers": numbers, "selected": selected}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    context = page_context() | district_numbers("house", None)
    return templates.TemplateResponse(request, "home.html", context)


@app.get("/picker/numbers", response_class=HTMLResponse)
def picker_numbers(request: Request, chamber: str = "", n: str | None = None) -> HTMLResponse:
    """htmx partial: the district-number select for the chosen chamber."""
    if chamber not in DISTRICT_COUNTS:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request, "partials/district_number.html", district_numbers(chamber, n)
    )


@app.get("/brief")
def pick(chamber: str = "", n: str = "") -> RedirectResponse:
    """The picker form's no-JavaScript target: redirect to the canonical brief URL."""
    state = page_state(chamber, n)
    if state is None:
        raise HTTPException(status_code=404)
    district = state.district
    return RedirectResponse(f"/brief/{district.chamber}/{district.district}", status_code=303)


@app.get("/brief/{chamber}/{n}", response_class=HTMLResponse)
def brief(request: Request, chamber: str, n: str, v: str | None = None) -> HTMLResponse:
    state = page_state(chamber, n, v)
    if state is None:
        raise HTTPException(status_code=404)
    sections = [
        Markup(templates.get_template(section.template).render(render_context(section, state)))
        for section in discover()
    ]
    context = page_context()
    title: str = load_copy()["brief"]["title"]
    context |= {
        "state": state,
        "sections": sections,
        "title": title.format(district=geography_name(state.district.fact_key)),
    }
    return templates.TemplateResponse(request, "brief.html", context)
