"""Suggested next steps on a saved folder card (#154): show, accept and dismiss, behind `folders`.

`GET /f/{folder}/cards/{card}/suggestions` answers the card's suggestions partial, which
`partials/folder-case.html` loads with htmx 2.0 (`hx-trigger="load"`) and links to without it.
Every card gets them, a legacy case card or a match card of any band: the proposals are the
matches the tool offers the card's district now (`app/tools/suggestions.py`), less the ones this
folder dismissed; those already in the folder say so instead of offering a decision.

`POST …/suggestions/accept` and `…/suggestions/dismiss` take `population_id`, `program_id`,
`source` and `dated`. Before any write they are checked against the proposals offered now, so a
forged or stale reference is refused with a message naming what is valid. A decision spends the
folder write limit and goes through `FolderStore.decide`, in the demo's copy when the folder is
the demo; accepting saves the match as a card, the next step. No model writes a word here and no
email is sent: the outreach email is a `mailto:` link the office opens itself.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.copy import Copy, load_copy
from app.folders.references import decode_match
from app.folders.routes import (
    TRUSTED_PROXIES,
    card_id_or_404,
    folder_id_or_404,
    folder_path,
    form_fields,
    guard,
    known_folder,
    open_store,
    refused,
    write_service,
)
from app.folders.service import client_ip
from app.folders.store import Card, Folder
from app.suggestions import Decision, SuggestionReference
from app.tools.matches import MatchReference
from app.tools.suggestions import Proposal, Source, propose
from etl.boundaries import DistrictId

FIELDS = ("population_id", "program_id", "source", "dated")
ACTIONS: dict[str, Decision] = {"accept": "accepted", "dismiss": "dismissed"}
# Checked on the raw value: nothing is trimmed or decoded before this.
UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029?#%]")

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")


@dataclass(frozen=True)
class Offer:
    proposal: Proposal
    in_folder: bool


def live_card(folder: Folder, card_id: int) -> Card:
    """A live card of this folder, or 404: another folder's card is unknown here."""
    card = next((card for card in folder.cards if card.id == card_id), None)
    if card is None:
        raise HTTPException(status_code=404)
    return card


def district_of(card: Card) -> DistrictId:
    return DistrictId(chamber=card.chamber, district=card.district)


def in_folder(
    folder: Folder, district: DistrictId, proposals: tuple[Proposal, ...]
) -> list[MatchReference]:
    """Proposals this folder holds already: a saved match, or the match a saved case names."""
    # Local: importing this router must leave case loading to `validate_startup`.
    from app.cases import load_cases

    cases = {case.id: case for case in load_cases().cases}
    held: list[MatchReference] = []
    for card in folder.cards:
        if district_of(card) != district:
            continue
        reference = decode_match(card.case_id, card.chamber, card.district)
        if reference is not None:
            held.append(reference)
        elif card.case_id in cases:
            case = cases[card.case_id]
            held.extend(
                p.match
                for p in proposals
                if p.match.population_id == case.population
                and p.card.match.official_url == case.program.url
            )
    return held


def read_reference(form: dict[str, str], proposals: tuple[Proposal, ...]) -> SuggestionReference:
    """Every check before any write, one refusal each, naming what to send instead."""
    words: Copy = load_copy()["suggestions"]
    if unknown := sorted(set(form) - set(FIELDS)):
        raise refused(
            words["unknown_fields"].format(fields=", ".join(unknown), valid=", ".join(FIELDS))
        )
    if missing := [name for name in FIELDS if name not in form]:
        raise refused(
            words["incomplete"].format(fields=", ".join(missing), valid=", ".join(FIELDS))
        )
    if any(UNSAFE.search(form[name]) for name in FIELDS):
        raise refused(words["bad_value"])
    sources = get_args(Source)
    if form["source"] not in sources:
        valid = ", ".join(sources)
        raise refused(words["unknown_source"].format(value=form["source"], valid=valid))
    chosen = next(
        (
            p
            for p in proposals
            if (p.match.population_id, p.match.program_id)
            == (form["population_id"], form["program_id"])
        ),
        None,
    )
    if chosen is None:
        valid = ", ".join(f"{p.match.population_id} · {p.match.program_id}" for p in proposals)
        message = words["unknown"].format(
            population=form["population_id"], program=form["program_id"], valid=valid
        )
        raise refused(message)
    if form["dated"] != chosen.dated.isoformat():
        raise refused(words["stale"].format(value=form["dated"], dated=chosen.dated.isoformat()))
    return SuggestionReference(match=chosen.match, source=chosen.source, dated=chosen.dated)


@router.get("/f/{folder_id}/cards/{card_id}/suggestions", response_class=HTMLResponse)
def show_suggestions(
    request: Request, folder_id: str, card_id: str, preview: str | None = None
) -> HTMLResponse:
    state = guard(preview)
    folder_id, card_id_number = folder_id_or_404(folder_id), card_id_or_404(card_id)
    with known_folder():
        db = open_store(state)
        folder = db.get_folder(folder_id)
        decisions = db.list_decisions(folder_id)
    card = live_card(folder, card_id_number)
    district = district_of(card)
    proposals = propose(district)
    dismissed = [d.reference.match for d in decisions if d.decision == "dismissed"]
    held = in_folder(folder, district, proposals)
    offered = [Offer(p, p.match in held) for p in proposals if p.match not in dismissed]
    context = {
        "card_id": card.id,
        "folder_id": folder_id,
        "offered": offered,
        "preview": state.preview,
        "words": load_copy()["suggestions"],
    }
    return templates.TemplateResponse(request, "partials/suggestions.html", context)


@router.post("/f/{folder_id}/cards/{card_id}/suggestions/{action}")
async def decide(
    request: Request, folder_id: str, card_id: str, action: str, preview: str | None = None
) -> RedirectResponse:
    """Revalidate, spend the write limit, decide; then back to the card or the accepted card."""
    state = guard(preview)
    folder_id, card_id_number = folder_id_or_404(folder_id), card_id_or_404(card_id)
    decision = ACTIONS.get(action)
    if decision is None:
        raise HTTPException(status_code=404)
    form = await form_fields(request)
    folders = write_service(state)
    with known_folder():
        folder = folders.store.get_folder(folder_id)
    card = live_card(folder, card_id_number)
    reference = read_reference(form, propose(district_of(card)))
    with known_folder():
        folders.throttle_write(client_ip(request.scope, TRUSTED_PROXIES))
        with folders.store.visitor_write(folder_id) as write:
            folders.store.decide(write.folder_id, reference, decision)
            anchor = write.card(card.id)
        if decision == "accepted":
            decided = folders.store.list_decisions(write.folder_id)
            anchor = next(d.card_id for d in decided if d.reference == reference) or anchor
    return RedirectResponse(f"{folder_path(write.folder_id, state)}#card-{anchor}", status_code=303)
