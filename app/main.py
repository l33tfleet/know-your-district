"""ASGI entry point: `uvicorn app.main:app`.

Startup validates section declarations, their templates and features.toml before serving.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.brief import discover, render_section
from app.copy import geography_name, load_copy
from app.features import validate_features
from app.page_state import page_state
from etl.boundaries import DISTRICT_COUNTS

ROOT = Path(__file__).resolve().parent.parent
HTMX_VERSION = "2.0.11"
SITE_URL = "https://district.hawaiitechmentors.org"

TEMPLATES_DIR = ROOT / "templates"


def validate_startup() -> None:
    """Fail before serving on a malformed section, a missing template or an unknown flag.

    Discovery registers every section's FEATURE first, so features.toml may name them;
    any other name fails with the list of valid names.
    """
    missing = [s.template for s in discover() if not (TEMPLATES_DIR / s.template).is_file()]
    if missing:
        raise ValueError(
            f"Missing section templates: {', '.join(missing)}; "
            "each app/sections/NN_name.py needs templates/sections/NN-name.html"
        )
    validate_features()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    validate_startup()
    yield


app = FastAPI(title="Know Your District", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


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


@dataclass(frozen=True)
class BriefPart:
    """One section as the brief template shows it."""

    html: Markup | None
    printable: bool
    failure_note: str | None = None


def render_template(template: str, values: dict[str, object]) -> str:
    return templates.get_template(template).render(values)


@app.get("/brief/{chamber}/{n}", response_class=HTMLResponse)
def brief(
    request: Request, chamber: str, n: str, v: str | None = None, preview: str | None = None
) -> HTMLResponse:
    if preview not in (None, "0", "1"):
        raise HTTPException(status_code=404)
    state = page_state(chamber, n, v, preview=preview == "1")
    if state is None:
        raise HTTPException(status_code=404)
    copy = load_copy()
    failed: str = copy["brief"]["section_failed"]
    sections: list[BriefPart] = []
    for rendered in (render_section(s, state, render_template) for s in discover(state)):
        section = rendered.section
        if rendered.html is not None:
            sections.append(BriefPart(Markup(rendered.html), section.printable))
        elif state.preview:
            # Only preview readers learn that a flagged section failed; others see it omitted.
            note = failed.format(name=section.name.replace("_", " "))
            sections.append(BriefPart(None, False, note))
    context = page_context()
    title: str = copy["brief"]["title"]
    context |= {
        "state": state,
        "sections": sections,
        "title": title.format(district=geography_name(state.district.fact_key)),
    }
    return templates.TemplateResponse(request, "brief.html", context)
