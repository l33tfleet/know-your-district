"""District folder pages, behind the `folders` flag; every read and write goes through the store.

A folder is owned by its link. It holds case ids and districts, so each render re-reads every
figure through section 15. Without JavaScript a form posts and redirects; htmx gets the partial.
"""

import importlib
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import TypeAdapter, ValidationError

from app.copy import Copy, geography_name, load_copy, section_copy
from app.features import require_feature
from app.folders.store import (
    FEATURE,
    Card,
    CardId,
    FolderId,
    FolderNotFoundError,
    FolderStore,
    Priority,
    Reason,
    Status,
    StoreConfigError,
    default_path,
)
from app.page_state import PageState, page_state
from etl.boundaries import DISTRICT_COUNTS

PRIORITIES: TypeAdapter[Priority] = TypeAdapter(Priority)
STATUSES: TypeAdapter[Status] = TypeAdapter(Status)
REASONS: TypeAdapter[str] = TypeAdapter(Reason)
FOLDER_IDS: TypeAdapter[str] = TypeAdapter(FolderId)
CARD_IDS: TypeAdapter[int] = TypeAdapter(CardId)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")


def guard(preview: str | None) -> PageState:
    """404 while the flag is off, before any input is read, so off never reveals a route.

    A folder's district is on its cards, unknown here; the flag reads only `preview`.
    """
    if preview not in (None, "0", "1"):
        raise HTTPException(status_code=404)
    state = page_state("house", "1", preview=preview == "1")
    assert state is not None
    require_feature(FEATURE, state)
    return state


def open_store(state: PageState) -> FolderStore:
    path = os.environ.get("KYD_FOLDERS_DB")
    return FolderStore(Path(path) if path else default_path(), state)


@contextmanager
def known_folder() -> Generator[None]:
    """An unknown folder or card answers like any unknown page; a file refused at open, 503."""
    try:
        yield
    except FolderNotFoundError as exc:
        raise HTTPException(status_code=404) from exc
    except StoreConfigError as exc:
        raise HTTPException(status_code=503, detail=load_copy()["folders"]["no_store"]) from exc


def folder_id_or_404(text: str) -> str:
    try:
        return FOLDER_IDS.validate_python(text)
    except ValidationError as exc:
        raise HTTPException(status_code=404) from exc


def card_id_or_404(text: str) -> int:
    if not text.isascii() or not text.isdecimal():
        raise HTTPException(status_code=404)
    try:
        return CARD_IDS.validate_python(int(text))
    except ValidationError as exc:
        raise HTTPException(status_code=404) from exc


def refused(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


async def form_fields(request: Request) -> dict[str, str]:
    """URL-encoded fields, the one form encoding these pages send."""
    body = (await request.body()).decode("utf-8", "replace")
    return {name: values[-1] for name, values in parse_qs(body, keep_blank_values=True).items()}


def case_district(form: dict[str, str]) -> PageState:
    """Refuse a case or district the app does not know; the state carries the district."""
    # Local: `validate_startup` is the first to load the cases, never an import of `app.main`.
    from app.cases import load_cases

    words = load_copy()["folders"]
    valid = [record.id for record in load_cases().cases]
    case_id = form.get("case_id")
    if case_id not in valid:
        raise refused(words["unknown_case"].format(value=case_id, valid=", ".join(valid)))
    state = page_state(form.get("chamber", ""), form.get("district", ""))
    if state is None:
        raise refused(words["unknown_district"].format(valid=", ".join(DISTRICT_COUNTS)))
    return state


def query_of(state: PageState) -> str:
    return "?preview=1" if state.preview else ""


def folder_path(folder_id: str, state: PageState) -> str:
    return f"/f/{folder_id}{query_of(state)}"


def render_card(card: Card, state: PageState, folder_id: str) -> Markup:
    """Section 15's own card and template, read fresh, above this folder's saved state."""
    words: Copy = load_copy()["folders"]
    card_state = page_state(card.chamber, str(card.district), preview=state.preview)
    assert card_state is not None
    build = cast(
        Callable[[PageState, str], dict[str, object]],
        importlib.import_module("app.sections.15_case").case_card,
    )
    section = build(card_state, card.case_id)
    if section:
        brief = f"/brief/{card.chamber}/{card.district}{query_of(state)}"
        section |= {
            "heading_id": f"case-heading-{card.id}",
            "evidence_href": f"{brief}#outreach-heading",
        }
    html = templates.get_template("sections/15-case.html").render(
        section=section, copy=section_copy("case"), state=card_state
    )
    reason = words["summary_reason"].format(reason=card.reason) if card.reason else ""
    summary = words["summary"].format(
        priority=words["priorities"][card.priority],
        reason=reason,
        status=words["statuses"][card.status],
    )
    return Markup(
        templates.get_template("partials/folder-case.html").render(
            card=card,
            card_html=Markup(html),
            district_line=words["district_label"].format(
                district=geography_name(card_state.district.fact_key)
            ),
            folder_id=folder_id,
            preview=state.preview,
            summary=summary,
            words=words,
        )
    )


def after_write(request: Request, state: PageState, folder_id: str, card_id: int) -> Response:
    """htmx swaps the summary out of the card partial; a plain form goes back to the folder."""
    if request.headers.get("HX-Request") != "true":
        return RedirectResponse(folder_path(folder_id, state), status_code=303)
    with known_folder():
        folder = open_store(state).get_folder(folder_id)
    card = next(card for card in folder.cards if card.id == card_id)
    return HTMLResponse(render_card(card, state, folder_id))


@router.post("/folders")
async def create_folder(request: Request, preview: str | None = None) -> RedirectResponse:
    state = guard(preview)
    form = await form_fields(request)
    district = case_district(form).district
    name = geography_name(district.fact_key)
    with known_folder():
        folder_id = open_store(state).create_folder(
            name, form["case_id"], district.chamber, int(district.district)
        )
    return RedirectResponse(folder_path(folder_id, state), status_code=303)


@router.get("/f/{folder_id}", response_class=HTMLResponse)
def show_folder(request: Request, folder_id: str, preview: str | None = None) -> HTMLResponse:
    state = guard(preview)
    folder_id = folder_id_or_404(folder_id)
    with known_folder():
        folder = open_store(state).get_folder(folder_id)
    # Local: `app.main` includes this router at import time.
    from app.main import page_context

    words: Copy = load_copy()["folders"]
    context = page_context() | {
        "cards": [render_card(card, state, folder_id) for card in folder.cards],
        "folder": folder,
        "link": str(request.url),
        "reopen": folder_path(folder_id, state),
        "title": words["title"].format(name=folder.name),
        "words": words,
    }
    return templates.TemplateResponse(request, "folder.html", context)


@router.post("/f/{folder_id}/cases")
async def save_case(request: Request, folder_id: str, preview: str | None = None) -> Response:
    state = guard(preview)
    folder_id = folder_id_or_404(folder_id)
    form = await form_fields(request)
    district = case_district(form).district
    with known_folder():
        open_store(state).save_case(
            folder_id, form["case_id"], district.chamber, int(district.district)
        )
    return RedirectResponse(folder_path(folder_id, state), status_code=303)


@router.post("/f/{folder_id}/cards/{card_id}/priority")
async def set_priority(
    request: Request, folder_id: str, card_id: str, preview: str | None = None
) -> Response:
    state = guard(preview)
    folder_id, card = folder_id_or_404(folder_id), card_id_or_404(card_id)
    form = await form_fields(request)
    words = load_copy()["folders"]
    priority = form.get("priority")
    try:
        chosen = PRIORITIES.validate_python(priority)
    except ValidationError as exc:
        valid = ", ".join(words["priorities"])
        raise refused(words["unknown_priority"].format(value=priority, valid=valid)) from exc
    try:
        reason = REASONS.validate_python(form.get("reason"))
    except ValidationError as exc:
        raise refused(words["bad_reason"]) from exc
    with known_folder():
        open_store(state).set_priority(folder_id, card, chosen, reason)
    return after_write(request, state, folder_id, card)


@router.post("/f/{folder_id}/cards/{card_id}/status")
async def set_status(
    request: Request, folder_id: str, card_id: str, preview: str | None = None
) -> Response:
    state = guard(preview)
    folder_id, card = folder_id_or_404(folder_id), card_id_or_404(card_id)
    form = await form_fields(request)
    words = load_copy()["folders"]
    status = form.get("status")
    try:
        chosen = STATUSES.validate_python(status)
    except ValidationError as exc:
        valid = ", ".join(words["statuses"])
        raise refused(words["unknown_status"].format(value=status, valid=valid)) from exc
    with known_folder():
        open_store(state).set_status(folder_id, card, chosen)
    return after_write(request, state, folder_id, card)
