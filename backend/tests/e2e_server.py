"""Stub-backed API server for the Playwright suite (task 10.4).

Covers R-12.2, R-12.6; NFR-03, NFR-04, NFR-05, NFR-09, NFR-10.
Run with ``uvicorn tests.e2e_server:app``. It uses the deterministic stub model and an
in-memory store, so no AWS call is ever made. ``E2E_BACKEND_MODE`` selects the behavior:

* ``ok`` (default): the stub model succeeds. A wrong answer of ``9`` has no deterministic
  verdict, so the stub Assessment_Specialist returns a scripted misconception and the next
  Activity is adapted (R-06.2).
* ``fail``: every model call fails, which drives the model-failure error flow.

``POST /__e2e/expire/{session_id}`` back-dates ``expires_at`` so the expired-session flow can be
exercised without waiting 24 hours. It exists only in this test server, never in ``app.main``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from app.adapters.bedrock import ResilientModelClient, StubModel
from app.adapters.session_store import InMemorySessionStore
from app.agents.assessment import AssessmentSpecialist
from app.agents.curriculum import CurriculumSpecialist
from app.agents.environment import EnvironmentSpecialist
from app.agents.orchestrator import Orchestrator
from app.agents.storytelling import StorytellingSpecialist
from app.config import Settings
from app.domain.models import Activity, Assessment, AssessmentOutput, AssessmentStatus, Grade
from app.main import create_app
from app.services import grading
from app.services.assessment_service import AssessmentService
from app.services.learning_loop import LearningLoopService, orchestrator_assessor
from app.services.lesson_service import LessonService
from app.services.session_service import SessionService
from fastapi import FastAPI

MODE = os.environ.get("E2E_BACKEND_MODE", "ok")
SCRIPTED_WRONG_ANSWER = "9"


async def _no_sleep(_: float) -> None:
    return None


def _grade(activity: Activity, answer: str, spelling_matters: bool) -> Grade | None:
    """Defer the scripted wrong answer to the specialist; grade everything else exactly."""
    if answer.strip() == SCRIPTED_WRONG_ANSWER:
        return None
    return grading.grade(activity, answer, spelling_matters)


def build_app() -> FastAPI:
    settings = Settings(
        use_stub_model=True,
        model_retry_backoff_seconds=0,
        specialist_retries=0,
        lesson_generation_retries=0,
        rate_limit_per_minute=100_000,
    )
    scripted = AssessmentOutput(
        assessment=Assessment(
            status=AssessmentStatus.SUPPORT,
            explanation="Close. Let's count together, one at a time.",
            misconception="Skipped one item while counting.",
            suggested_scaffold="Touch each item once as you count aloud.",
            confidence=0.9,
        )
    ).model_dump(mode="json")
    raw = (
        StubModel(failures=None)
        if MODE == "fail"
        else StubModel(overrides={"AssessmentOutput": scripted})
    )
    client = ResilientModelClient(raw, settings, sleep=_no_sleep)
    orchestrator = Orchestrator(
        environment=EnvironmentSpecialist(client),
        curriculum=CurriculumSpecialist(client),
        storytelling=StorytellingSpecialist(client),
        assessment=AssessmentSpecialist(client),
        settings=settings,
    )
    store = InMemorySessionStore(ttl=timedelta(hours=settings.session_ttl_hours))
    app = create_app(
        settings,
        session_store=store,
        session_service=SessionService(store),
        lesson_service=LessonService(store, orchestrator, settings),
        learning_service=LearningLoopService(
            store,
            AssessmentService(orchestrator_assessor(orchestrator, settings), grade_fn=_grade),
            settings,
        ),
    )

    @app.post("/__e2e/expire/{session_id}", status_code=204)
    def expire(session_id: str) -> None:
        record = store._items[session_id]
        store._items[session_id] = record.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )

    return app


app = build_app()
