"""ASGI entry point: `uvicorn app.main:app`."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
HTMX_VERSION = "2.0.11"
SITE_URL = "https://district.hawaiitechmentors.org"

app = FastAPI(title="Know Your District", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


class Health(BaseModel):
    status: str


@app.get("/healthz")
def healthz() -> Health:
    return Health(status="ok")


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "home.html",
        {"htmx_src": f"/static/vendor/htmx-{HTMX_VERSION}.min.js", "site_url": SITE_URL},
    )
