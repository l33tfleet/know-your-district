"""District folder pages, behind the `folders` flag; every read and write goes through the store.

A folder is owned by its link. It holds case ids and districts, so each render re-reads every
figure through section 15. Without JavaScript a form posts and redirects; htmx gets the partial.

Notes take two posts: the first checks the words and, when they are clean, answers with a confirm
step carrying a token for exactly those words; the second sends the token back and saves. A
personal detail is always refused (`app/folders/notes.py`). Delete needs no confirmation.
"""

import importlib
import os
from collections.abc import Callable, Generator, Sequence
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
from app.folders import notes
from app.folders.notes import Draft
from app.folders.service import FolderService, Network, client_ip, load_secret
from app.folders.store import (
    FEATURE,
    Card,
    CardId,
    FolderId,
    FolderNotFoundError,
    FolderStore,
    Note,
    NoteId,
    Priority,
    RateLimitedError,
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
NOTE_IDS: TypeAdapter[int] = TypeAdapter(NoteId)
# No proxy is trusted yet, so behind one every office shares the proxy's write count.
TRUSTED_PROXIES: tuple[Network, ...] = ()

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
    """An unknown folder or card answers like any unknown page; a file refused at open, 503.

    A request limit answers 429 with the seconds to wait.
    """
    try:
        yield
    except FolderNotFoundError as exc:
        raise HTTPException(status_code=404) from exc
    except StoreConfigError as exc:
        raise HTTPException(status_code=503, detail=load_copy()["folders"]["no_store"]) from exc
    except RateLimitedError as exc:
        seconds = exc.retry_after_seconds
        raise HTTPException(
            status_code=429,
            detail=load_copy()["folders"]["note_rate"].format(seconds=seconds),
            headers={"Retry-After": str(seconds)},
        ) from exc


def note_service(state: PageState) -> FolderService:
    """Notes need `KYD_FOLDERS_SECRET` for their confirmations and counts; without it, 503."""
    try:
        secret = load_secret()
    except StoreConfigError as exc:
        raise HTTPException(status_code=503, detail=load_copy()["folders"]["no_secret"]) from exc
    with known_folder():
        return FolderService(open_store(state), secret)


def folder_id_or_404(text: str) -> str:
    try:
        return FOLDER_IDS.validate_python(text)
    except ValidationError as exc:
        raise HTTPException(status_code=404) from exc


def id_or_404(text: str, ids: TypeAdapter[int]) -> int:
    if not text.isascii() or not text.isdecimal():
        raise HTTPException(status_code=404)
    try:
        return ids.validate_python(int(text))
    except ValidationError as exc:
        raise HTTPException(status_code=404) from exc


def card_id_or_404(text: str) -> int:
    return id_or_404(text, CARD_IDS)


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


def render_notes(
    state: PageState,
    folder_id: str,
    card_id: int,
    saved: Sequence[Note],
    draft: Draft | None = None,
    open_editor: int | None = None,
) -> Markup:
    """One card's notes and its note box; the template orders them newest first.

    `open_editor` is the note whose edit box shows; the others offer a link that opens it.
    """
    return Markup(
        templates.get_template("partials/folder-notes.html").render(
            card_id=card_id,
            date_label=notes.date_label,
            draft=draft if draft is not None and draft.card_id == card_id else None,
            folder_href=folder_path(folder_id, state),
            folder_id=folder_id,
            notes=[note for note in saved if note.card_id == card_id],
            open_editor=open_editor,
            preview=state.preview,
            words=load_copy()["folders"],
        )
    )


def folder_page(
    request: Request,
    state: PageState,
    folder_id: str,
    draft: Draft | None = None,
    status_code: int = 200,
    open_editor: int | None = None,
) -> HTMLResponse:
    """The folder with each card and its notes; a draft shows under its own card."""
    with known_folder():
        db = open_store(state)
        folder = db.get_folder(folder_id)
        saved = db.list_notes(folder_id)
    # Local: `app.main` includes this router at import time.
    from app.main import page_context

    words: Copy = load_copy()["folders"]
    # The link to share is the folder's, never a form's address or an open editor's.
    link = str(request.base_url).rstrip("/") + folder_path(folder_id, state)
    context = page_context() | {
        "cards": [
            {
                "card": render_card(card, state, folder_id),
                "notes": render_notes(state, folder_id, card.id, saved, draft, open_editor),
            }
            for card in folder.cards
        ],
        "folder": folder,
        "link": link,
        "reopen": folder_path(folder_id, state),
        "title": words["title"].format(name=folder.name),
        "words": words,
    }
    return templates.TemplateResponse(request, "folder.html", context, status_code=status_code)


def after_write(request: Request, state: PageState, folder_id: str, card_id: int) -> Response:
    """htmx swaps the summary out of the card partial; a plain form goes back to the folder."""
    if request.headers.get("HX-Request") != "true":
        return RedirectResponse(folder_path(folder_id, state), status_code=303)
    with known_folder():
        folder = open_store(state).get_folder(folder_id)
    card = next(card for card in folder.cards if card.id == card_id)
    return HTMLResponse(render_card(card, state, folder_id))


def after_note(
    request: Request, state: PageState, folder_id: str, card_id: int, draft: Draft | None
) -> Response:
    """htmx swaps the card's notes; a plain form sees its draft on the folder, else goes back."""
    status_code = 422 if draft is not None and draft.refusal else 200
    if request.headers.get("HX-Request") == "true":
        with known_folder():
            saved = open_store(state).list_notes(folder_id)
        html = render_notes(state, folder_id, card_id, saved, draft)
        return HTMLResponse(html, status_code=status_code)
    if draft is not None:
        return folder_page(request, state, folder_id, draft, status_code)
    return RedirectResponse(folder_path(folder_id, state), status_code=303)


def write_note(
    request: Request,
    state: PageState,
    folders: FolderService,
    folder_id: str,
    card_id: int,
    note_id: int | None,
    form: dict[str, str],
) -> Response:
    """No confirmation yet: the check step. With one: the save, which screens the words again."""
    words: Copy = load_copy()["folders"]
    body = notes.read_body(form)
    confirmation = form.get("confirmation")
    if confirmation is None:
        draft = notes.check(folders, folder_id, card_id, note_id, body, words)
        return after_note(request, state, folder_id, card_id, draft)
    ip = client_ip(request.scope, TRUSTED_PROXIES)
    try:
        with known_folder():
            if note_id is None:
                folders.add_note(folder_id, card_id, body, confirmation, ip)
            else:
                folders.edit_note(folder_id, note_id, body, confirmation, ip)
    except notes.REFUSALS as exc:
        message = notes.refusal(body, exc, words)
        draft = Draft(card_id=card_id, note_id=note_id, body=body, refusal=message)
        return after_note(request, state, folder_id, card_id, draft)
    return after_note(request, state, folder_id, card_id, None)


def live_note(folders: FolderService, folder_id: str, note_id: int) -> Note:
    """A live note of this folder, or 404: another folder's note is unknown here."""
    with known_folder():
        saved = folders.store.list_notes(folder_id)
    found = next((note for note in saved if note.id == note_id), None)
    if found is None:
        raise HTTPException(status_code=404)
    return found


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
def show_folder(
    request: Request, folder_id: str, preview: str | None = None, edit: str | None = None
) -> HTMLResponse:
    """`?edit=<note>` opens that note's edit box; htmx selects the card's notes from the page."""
    state = guard(preview)
    folder_id = folder_id_or_404(folder_id)
    editor = None if edit is None else id_or_404(edit, NOTE_IDS)
    return folder_page(request, state, folder_id, open_editor=editor)


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


@router.post("/f/{folder_id}/cards/{card_id}/notes")
async def add_note(
    request: Request, folder_id: str, card_id: str, preview: str | None = None
) -> Response:
    state = guard(preview)
    folder_id, card = folder_id_or_404(folder_id), card_id_or_404(card_id)
    form = await form_fields(request)
    folders = note_service(state)
    with known_folder():
        cards = folders.store.get_folder(folder_id).cards
    if card not in {saved.id for saved in cards}:
        raise HTTPException(status_code=404)
    return write_note(request, state, folders, folder_id, card, None, form)


@router.post("/f/{folder_id}/notes/{note_id}")
async def edit_note(
    request: Request, folder_id: str, note_id: str, preview: str | None = None
) -> Response:
    state = guard(preview)
    folder_id, note = folder_id_or_404(folder_id), id_or_404(note_id, NOTE_IDS)
    form = await form_fields(request)
    folders = note_service(state)
    card = live_note(folders, folder_id, note).card_id
    return write_note(request, state, folders, folder_id, card, note, form)


@router.post("/f/{folder_id}/notes/{note_id}/delete")
async def delete_note(
    request: Request, folder_id: str, note_id: str, preview: str | None = None
) -> Response:
    """No confirmation: removing words adds no personal detail. It still counts as a write."""
    state = guard(preview)
    folder_id, note = folder_id_or_404(folder_id), id_or_404(note_id, NOTE_IDS)
    folders = note_service(state)
    card = live_note(folders, folder_id, note).card_id
    with known_folder():
        folders.throttle_write(client_ip(request.scope, TRUSTED_PROXIES))
        folders.store.delete_note(folder_id, note)
    return after_note(request, state, folder_id, card, None)
