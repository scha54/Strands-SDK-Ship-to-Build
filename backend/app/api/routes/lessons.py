"""Lesson routes: start generation and poll sanitized stage events.

* ``POST /sessions/{id}/lessons`` (R-03, R-04, R-11.1, R-11.2) is idempotent through the
  ``Idempotency-Key`` header. It reserves the Session (``GENERATING``), returns 202 and runs the
  generation after the response. A repeated key and payload returns 202 again without
  regenerating. The per-session generation cap and PII checks reject before any model call.
* ``GET /sessions/{id}/events`` (R-04.5, R-12.3) returns the sanitized Stage_Events plus the
  Session state. On failure it names the options (retry, safe_template); the Lesson text itself is
  served by the learner view, not here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict

from app.api.auth import AuthenticatedSession
from app.domain.models import AgentStageEvent
from app.services.demo_seed import DEMO_FALLBACK_LABEL
from app.services.lesson_service import LessonService, Mode
from app.services.safe_templates import SAFE_TEMPLATE_LABEL

router = APIRouter(prefix="/api/v1", tags=["lessons"])


def get_lesson_service(request: Request) -> LessonService:
    service = getattr(request.app.state, "lesson_service", None)
    if not isinstance(service, LessonService):  # pragma: no cover - configuration guard
        raise RuntimeError("lesson_service is not configured on app.state")
    return service


class StartLessonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = "generate"


class LessonAccepted(BaseModel):
    session_id: str
    state: str
    replayed: bool
    warnings: list[str]
    events_url: str


class EventsView(BaseModel):
    state: str
    events: list[AgentStageEvent]
    lesson_source: Literal["generated", "safe_template", "demo_fallback"] | None = None
    label: str | None = None
    error_code: str | None = None
    options: list[str] = []


@router.post("/sessions/{session_id}/lessons", status_code=status.HTTP_202_ACCEPTED)
def start_lesson(
    session: AuthenticatedSession,
    background: BackgroundTasks,
    service: Annotated[LessonService, Depends(get_lesson_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    body: StartLessonRequest | None = None,
) -> LessonAccepted:
    mode: Mode = body.mode if body else "generate"
    result = service.start(session.session_id, idempotency_key, mode)
    if not result.replayed:
        background.add_task(service.run, session.session_id, mode)
    return LessonAccepted(
        session_id=session.session_id,
        state=result.state,
        replayed=result.replayed,
        warnings=result.warnings,
        events_url=f"/api/v1/sessions/{session.session_id}/events",
    )


def _label(source: str | None) -> str | None:
    if source == "safe_template":
        return SAFE_TEMPLATE_LABEL
    if source == "demo_fallback":
        return DEMO_FALLBACK_LABEL
    return None


@router.get("/sessions/{session_id}/events")
def get_events(
    session: AuthenticatedSession,
    service: Annotated[LessonService, Depends(get_lesson_service)],
) -> EventsView:
    failure = service.last_failure(session.session_id) if session.state == "failed" else None
    lesson = session.lesson
    return EventsView(
        state=session.state,
        events=session.stage_events,
        lesson_source=lesson.source if lesson else None,
        label=_label(lesson.source if lesson else None),
        error_code=failure[0] if failure else None,
        options=list(failure[1]) if failure else [],
    )
