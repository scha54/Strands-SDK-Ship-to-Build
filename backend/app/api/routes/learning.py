"""Learning-loop routes: baseline, answers, hints, advance, end check and summary.

Covers R-05.2 to R-05.8, R-07.1, R-07.2, R-07.6, R-08.3, R-10.9; NFR-02, NFR-05.
Every route needs the Capability_Token. Writes are rejected with 409 ``session_stopped`` once the
Session is stopped; reads stay available for review.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.api.auth import AuthenticatedSession
from app.domain.models import AnswerRequest, SessionSummary
from app.services.learner_view import LearnerView
from app.services.learning_loop import (
    AdvanceRequest,
    AdvanceResult,
    AnswerResult,
    HintResult,
    LearningLoopService,
    QuestionAnswer,
    QuestionResult,
    QuestionView,
)

router = APIRouter(prefix="/api/v1", tags=["learning"])


def get_learning_service(request: Request) -> LearningLoopService:
    service = getattr(request.app.state, "learning_service", None)
    if not isinstance(service, LearningLoopService):  # pragma: no cover - configuration guard
        raise RuntimeError("learning_service is not configured on app.state")
    return service


Learning = Annotated[LearningLoopService, Depends(get_learning_service)]


@router.get("/sessions/{session_id}/learner-view")
def get_learner_view(session: AuthenticatedSession, service: Learning) -> LearnerView:
    return service.learner_view(session)


@router.get("/sessions/{session_id}/baseline")
def get_baseline_question(session: AuthenticatedSession, service: Learning) -> QuestionView:
    return service.baseline_question(session)


@router.post("/sessions/{session_id}/baseline")
def post_baseline(
    session: AuthenticatedSession, body: QuestionAnswer, service: Learning
) -> QuestionResult:
    return service.submit_baseline(session.session_id, body)


@router.post("/sessions/{session_id}/answers")
async def post_answer(
    session: AuthenticatedSession,
    body: AnswerRequest,
    service: Learning,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> AnswerResult:
    return await service.submit_answer(session.session_id, idempotency_key, body.answer)


@router.post("/sessions/{session_id}/hint")
def post_hint(session: AuthenticatedSession, service: Learning) -> HintResult:
    return service.hint(session.session_id)


@router.post("/sessions/{session_id}/advance")
def post_advance(
    session: AuthenticatedSession, body: AdvanceRequest, service: Learning
) -> AdvanceResult:
    return service.advance(session.session_id, body)


@router.get("/sessions/{session_id}/end-check")
def get_end_question(session: AuthenticatedSession, service: Learning) -> QuestionView:
    return service.end_question(session)


@router.post("/sessions/{session_id}/end-check")
def post_end_check(
    session: AuthenticatedSession, body: QuestionAnswer, service: Learning
) -> QuestionResult:
    return service.submit_end_check(session.session_id, body)


@router.get("/sessions/{session_id}/summary")
def get_summary(session: AuthenticatedSession, service: Learning) -> SessionSummary:
    return service.summary(session)
