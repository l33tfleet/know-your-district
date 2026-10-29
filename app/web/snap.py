"""htmx partial: the answer to the brief's fixed SNAP question, behind the snap_question flag.

The answer comes from app/tools/snap.py, which reads the published fact table; no model call.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.copy import section_copy
from app.features import register_feature, require_feature
from app.page_state import page_state
from app.tools.snap import DistrictSnap, Question

FEATURE = "snap_question"
register_feature(FEATURE)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")


@router.get("/brief/{chamber}/{n}/snap-answer", response_class=HTMLResponse)
def snap_answer(
    request: Request,
    chamber: str,
    n: str,
    question: str | None = None,
    v: str | None = None,
    preview: str | None = None,
) -> HTMLResponse:
    """A disabled feature answers 404 before the question is checked, so it stays hidden."""
    if preview not in (None, "0", "1"):
        raise HTTPException(status_code=404)
    state = page_state(chamber, n, v, preview=preview == "1")
    if state is None:
        raise HTTPException(status_code=404)
    require_feature(FEATURE, state)
    if question not in tuple(Question):
        valid = ", ".join(Question)
        raise HTTPException(
            status_code=422, detail=f"Unknown question {question!r}; valid questions: {valid}"
        )
    context = {
        "answer": DistrictSnap(state.district).answer(),
        "copy": section_copy("snap_question"),
        "figures_copy": section_copy("figures"),
    }
    return templates.TemplateResponse(request, "partials/snap-answer.html", context)
