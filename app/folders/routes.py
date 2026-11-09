"""District folder pages, behind the `folders` flag; every read and write goes through the store.

A folder is owned by its link. It holds case ids, match identities and districts, so each render
re-reads every figure: a case through section 15, a match through the matching tool and the
shared card partial. Without JavaScript a form posts and redirects; htmx gets the partial.

Every card surface posts one save form to `POST /folders`: a case (`case_id`, `chamber`,
`district`) or a match (`population_id`, `program_id`, with `?district=house-22`), plus an
optional `folder` link to save into an existing folder. No selection starts an empty folder.
Creations spend the creation limits and every other write spends the write limit, both keyed by
`KYD_FOLDERS_SECRET`; without it, writes answer 503.

Notes take two posts: the first checks the words and, when they are clean, answers with a confirm
step carrying a token for exactly those words; the second sends the token back and saves. A
personal detail is always refused (`app/folders/notes.py`). Delete needs no confirmation.
"""

import importlib
import os
import re
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import TypeAdapter, ValidationError

from app.copy import Copy, geography_name, load_copy, section_copy
from app.features import enabled, require_feature
from app.folders import notes
from app.folders.attention import needs_attention
from app.folders.notes import Draft
from app.folders.references import decode_match, encode_match
from app.folders.service import FolderService, Network, client_ip, load_secret
from app.folders.store import (
    FEATURE,
    CapacityError,
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
from app.populations import load_populations
from app.tools.matches import CATALOG, DistrictMatches, MatchReference, find_matches
from etl.boundaries import DISTRICT_COUNTS
from etl.programs import load_catalog

PRIORITIES: TypeAdapter[Priority] = TypeAdapter(Priority)
STATUSES: TypeAdapter[Status] = TypeAdapter(Status)
REASONS: TypeAdapter[str] = TypeAdapter(Reason)
FOLDER_IDS: TypeAdapter[str] = TypeAdapter(FolderId)
CARD_IDS: TypeAdapter[int] = TypeAdapter(CardId)
NOTE_IDS: TypeAdapter[int] = TypeAdapter(NoteId)
# No proxy is trusted yet, so behind one every office shares the proxy's write count.
TRUSTED_PROXIES: tuple[Network, ...] = ()
SAVE_FIELDS = ("case_id", "chamber", "district", "population_id", "program_id", "folder")
# A folder link as the folder page shows it, or its bare id; nothing else is guessed at.
FOLDER_LINK = re.compile(
    r"(?:https?://[^/\s?#%]+)?/f/(?P<linked>[0-9a-f]{32})(?:\?preview=1)?|(?P<bare>[0-9a-f]{32})"
)

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
    except CapacityError as exc:
        detail = load_copy()["folders"]["capacity"].format(detail=exc)
        raise HTTPException(status_code=422, detail=detail) from exc
    except RateLimitedError as exc:
        seconds = exc.retry_after_seconds
        raise HTTPException(
            status_code=429,
            detail=load_copy()["folders"]["note_rate"].format(seconds=seconds),
            headers={"Retry-After": str(seconds)},
        ) from exc


def note_service(state: PageState, message: str = "no_secret") -> FolderService:
    """Writes need `KYD_FOLDERS_SECRET` for their counts, notes also for confirmations; else 503."""
    try:
        secret = load_secret()
    except StoreConfigError as exc:
        raise HTTPException(status_code=503, detail=load_copy()["folders"][message]) from exc
    with known_folder():
        return FolderService(open_store(state), secret)


def write_service(state: PageState) -> FolderService:
    return note_service(state, "no_write_secret")


def save_context(state: PageState, surface: str) -> dict[str, object]:
    """What the shared card partial needs for its save form; nothing while folders are off.

    `surface` keeps element ids unique when two surfaces show the same card on one page.
    """
    if not enabled(FEATURE, state):
        return {}
    district = state.district
    preview = "&preview=1" if state.preview else ""
    return {
        "save_words": section_copy("folder_save"),
        "save_action": f"/folders?district={district.chamber}-{district.district}{preview}",
        "save_surface": surface,
    }


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


def known_case(case_id: str | None) -> str:
    """Refuse a case the app does not know."""
    # Local: `validate_startup` is the first to load the cases, never an import of `app.main`.
    from app.cases import load_cases

    valid = [record.id for record in load_cases().cases]
    if case_id is None or case_id not in valid:
        words = load_copy()["folders"]
        raise refused(words["unknown_case"].format(value=case_id, valid=", ".join(valid)))
    return case_id


def district_of(chamber: str, number: str) -> PageState:
    state = page_state(chamber, number)
    if state is None:
        words = load_copy()["folders"]
        raise refused(words["unknown_district"].format(valid=", ".join(DISTRICT_COUNTS)))
    return state


def case_district(form: dict[str, str]) -> PageState:
    """Refuse a case or district the app does not know; the state carries the district."""
    known_case(form.get("case_id"))
    return district_of(form.get("chamber", ""), form.get("district", ""))


def match_reference(state: PageState, form: dict[str, str]) -> MatchReference:
    """A selection the matching tool offers this district now, or a refusal naming those."""
    words = load_copy()["folders"]
    population, program = form.get("population_id"), form.get("program_id")
    if population is None or program is None:
        raise refused(words["incomplete_match"])
    offered = find_matches(state.district)
    chosen = [r for r in offered if (r.population_id, r.program_id) == (population, program)]
    if not chosen:
        valid = ", ".join(f"{r.population_id} · {r.program_id}" for r in offered)
        message = words["unknown_match"].format(population=population, program=program, valid=valid)
        raise refused(message)
    return chosen[0]


def destination(form: dict[str, str]) -> str | None:
    """The existing folder a save goes into, from its pasted link; blank means a new folder."""
    text = form.get("folder", "").strip()
    if not text:
        return None
    found = FOLDER_LINK.fullmatch(text)
    if found is None:
        raise refused(load_copy()["folders"]["bad_folder"])
    return found["linked"] or found["bare"]


@dataclass(frozen=True)
class Selection:
    """One validated save: a case, a match or nothing, for one district, new or into `folder`."""

    district: PageState
    folder: str | None
    case_id: str | None = None
    match: MatchReference | None = None

    def key(self) -> str | None:
        """The card key the store keeps for this selection."""
        return encode_match(self.match) if self.match is not None else self.case_id


def read_selection(form: dict[str, str], district: str | None) -> Selection:
    """Every check before any write; each refusal names what to send instead."""
    words = load_copy()["folders"]
    unknown = sorted(set(form) - set(SAVE_FIELDS))
    if unknown:
        valid = ", ".join(SAVE_FIELDS)
        raise refused(words["unknown_fields"].format(fields=", ".join(unknown), valid=valid))
    is_match = "population_id" in form or "program_id" in form
    if is_match and "case_id" in form:
        raise refused(words["mixed_selection"])
    folder = destination(form)
    if district is not None and ("chamber" in form or "district" in form):
        raise refused(words["district_twice"])
    if district is None:
        state = district_of(form.get("chamber", ""), form.get("district", ""))
    else:
        chamber, _, number = district.partition("-")
        state = district_of(chamber, number)
    # A form carrying its own chamber and district is a case form: it needs its case. Only
    # `?district=` with no selection starts an empty folder.
    if "case_id" in form or (not is_match and district is None):
        return Selection(state, folder, case_id=known_case(form.get("case_id")))
    if is_match:
        return Selection(state, folder, match=match_reference(state, form))
    if folder is not None:
        raise refused(words["nothing_to_save"])
    return Selection(state, None)


def query_of(state: PageState) -> str:
    return "?preview=1" if state.preview else ""


def folder_path(folder_id: str, state: PageState) -> str:
    return f"/f/{folder_id}{query_of(state)}"


def render_case(card: Card, state: PageState, card_state: PageState) -> str:
    """Section 15's own card and template, read fresh."""
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
    return templates.get_template("sections/15-case.html").render(
        section=section, copy=section_copy("case"), state=card_state
    )


def render_match(reference: MatchReference) -> str:
    """The shared card partial over the matching tool's current result for this selection.

    A selection the tool no longer offers (its mapping was rejected, its program retired) shows
    a plain note and no figure; the office state above it is kept.
    """
    # Local: the card adapter imports the cases, which `validate_startup` loads first.
    from app.match_cards import to_match_card

    current = [
        match
        for match in DistrictMatches(reference.district).get_matches()
        if (match.population.id, match.program.id)
        == (reference.population_id, reference.program_id)
    ]
    if not current:
        return str(Markup("<p>{}</p>").format(load_copy()["folders"]["match_gone"]))
    return templates.get_template("partials/match_card.html").render(card=to_match_card(current[0]))


def card_names(cards: Sequence[Card]) -> dict[str, str]:
    """What the attention list calls each saved card, from the case and program records."""
    # Local: importing this router must leave case loading to `validate_startup`.
    from app.cases import load_cases

    names = {record.id: record.program.name for record in load_cases().cases}
    programs = {program.id: program.name for program in load_catalog(CATALOG)}
    populations = {population.id: population.label for population in load_populations().populations}
    for card in cards:
        reference = decode_match(card.case_id, card.chamber, card.district)
        if reference is not None:
            names[card.case_id] = (
                f"{programs[reference.program_id]} · {populations[reference.population_id]}"
            )
    return names


def render_card(card: Card, state: PageState, folder_id: str) -> Markup:
    """The saved card, read fresh, above this folder's saved state."""
    words: Copy = load_copy()["folders"]
    card_state = page_state(card.chamber, str(card.district), preview=state.preview)
    assert card_state is not None
    reference = decode_match(card.case_id, card.chamber, card.district)
    html = render_case(card, state, card_state) if reference is None else render_match(reference)
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
        "attention": needs_attention(folder.cards, saved, datetime.now(UTC).date()),
        "case_names": card_names(folder.cards),
        "geography_name": geography_name,
        "cards": [
            {
                "card": render_card(card, state, folder_id),
                "notes": render_notes(state, folder_id, card.id, saved, draft, open_editor),
            }
            for card in folder.cards
        ],
        "folder": folder,
        "link": link,
        "preview": state.preview,
        "reopen": folder_path(folder_id, state),
        "title": words["title"].format(name=folder.name),
        "words": words,
    }
    return templates.TemplateResponse(request, "folder.html", context, status_code=status_code)


def fork_redirect(
    request: Request, state: PageState, original: str, target: str
) -> Response | None:
    """Navigate the whole page so every remaining form uses the private link."""
    if original == target:
        return None
    path = folder_path(target, state)
    if request.headers.get("HX-Request") == "true":
        return Response(headers={"HX-Redirect": path})
    return RedirectResponse(path, status_code=303)


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
        with known_folder(), folders.confirmed_write(folder_id, body, confirmation, ip) as write:
            if note_id is None:
                folders.store.add_note(write.folder_id, write.card(card_id), body, True)
            else:
                folders.store.edit_note(write.folder_id, write.note(note_id), body, True)
    except notes.REFUSALS as exc:
        message = notes.refusal(body, exc, words)
        draft = Draft(card_id=card_id, note_id=note_id, body=body, refusal=message)
        return after_note(request, state, folder_id, card_id, draft)
    return fork_redirect(request, state, folder_id, write.folder_id) or after_note(
        request, state, folder_id, card_id, None
    )


def live_note(folders: FolderService, folder_id: str, note_id: int) -> Note:
    """A live note of this folder, or 404: another folder's note is unknown here."""
    with known_folder():
        saved = folders.store.list_notes(folder_id)
    found = next((note for note in saved if note.id == note_id), None)
    if found is None:
        raise HTTPException(status_code=404)
    return found


def saved_card(folders: FolderService, folder_id: str, chosen: Selection) -> int:
    """The live card holding this selection, after a save that may have kept an earlier one."""
    district = chosen.district.district
    with known_folder():
        cards = folders.store.get_folder(folder_id).cards
    return next(
        card.id
        for card in cards
        if (card.case_id, card.chamber, card.district)
        == (chosen.key(), district.chamber, int(district.district))
    )


@router.post("/folders")
async def create_folder(
    request: Request, preview: str | None = None, district: str | None = None
) -> RedirectResponse:
    """Start a folder (empty, with a case or with a match), or save into `folder`'s folder."""
    state = guard(preview)
    chosen = read_selection(await form_fields(request), district)
    folders = write_service(state)
    ip = client_ip(request.scope, TRUSTED_PROXIES)
    place = chosen.district.district
    number = int(place.district)
    with known_folder():
        if chosen.folder is not None:
            folders.throttle_write(ip)
            with folders.store.visitor_write(chosen.folder) as write:
                if chosen.match is not None:
                    folders.store.save_match(write.folder_id, chosen.match)
                else:
                    assert chosen.case_id is not None
                    folders.store.save_case(write.folder_id, chosen.case_id, place.chamber, number)
            card = saved_card(folders, write.folder_id, chosen)
            target = f"{folder_path(write.folder_id, state)}#card-{card}"
            return RedirectResponse(target, status_code=303)
        name = geography_name(place.fact_key)
        if chosen.match is not None:
            folder_id = folders.create_match_folder(name, chosen.match, ip)
        elif chosen.case_id is not None:
            folder_id = folders.create_folder(name, chosen.case_id, place.chamber, number, ip)
        else:
            folder_id = folders.create_empty_folder(name, ip)
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
    folders = write_service(state)
    with known_folder():
        folders.throttle_write(client_ip(request.scope, TRUSTED_PROXIES))
        db = folders.store
        with db.visitor_write(folder_id) as write:
            db.save_case(write.folder_id, form["case_id"], district.chamber, int(district.district))
    return fork_redirect(request, state, folder_id, write.folder_id) or RedirectResponse(
        folder_path(folder_id, state), status_code=303
    )


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
    # The reason is optional: none at all stores NULL; any text given meets every rule.
    reason = form.get("reason") or None
    try:
        reason = None if reason is None else REASONS.validate_python(reason)
    except ValidationError as exc:
        raise refused(words["bad_reason"]) from exc
    folders = write_service(state)
    with known_folder():
        folders.throttle_write(client_ip(request.scope, TRUSTED_PROXIES))
        db = folders.store
        with db.visitor_write(folder_id) as write:
            db.set_priority(write.folder_id, write.card(card), chosen, reason)
    return fork_redirect(request, state, folder_id, write.folder_id) or after_write(
        request, state, folder_id, card
    )


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
    folders = write_service(state)
    with known_folder():
        folders.throttle_write(client_ip(request.scope, TRUSTED_PROXIES))
        db = folders.store
        with db.visitor_write(folder_id) as write:
            db.set_status(write.folder_id, write.card(card), chosen)
    return fork_redirect(request, state, folder_id, write.folder_id) or after_write(
        request, state, folder_id, card
    )


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
        with folders.store.visitor_write(folder_id) as write:
            folders.store.delete_note(write.folder_id, write.note(note))
    return fork_redirect(request, state, folder_id, write.folder_id) or after_note(
        request, state, folder_id, card, None
    )
