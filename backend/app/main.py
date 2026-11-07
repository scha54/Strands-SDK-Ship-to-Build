"""Application factory: wires request-limit middleware, error handlers and health routes.

``create_app`` builds the FastAPI app, attaches the pure-ASGI request-limit middleware
(body size, concurrency, rate limit, correlation ID — all enforced before any handler,
R-11.4), registers the ``ApiError`` exception handlers (R-11.4) and mounts the health
routes (``/healthz`` R-11.5, ``/readyz`` R-11.6). The clock, client identifier and
readiness probes are injectable so limits and readiness are deterministic in tests.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI

from app.adapters.bedrock import create_model_client
from app.adapters.session_store import InMemorySessionStore, SessionStore
from app.agents.assessment import AssessmentSpecialist
from app.agents.curriculum import CurriculumSpecialist
from app.agents.environment import EnvironmentSpecialist
from app.agents.orchestrator import Orchestrator
from app.agents.storytelling import StorytellingSpecialist
from app.api.errors import install_error_handlers
from app.api.middleware import (
    ClientIdentifier,
    Clock,
    RequestLimitMiddleware,
    default_client_identifier,
    default_clock,
)
from app.api.routes import demo, health, learning, lessons, sessions
from app.config import Settings, get_settings
from app.services.assessment_service import AssessmentService
from app.services.demo_service import DemoService
from app.services.learning_loop import LearningLoopService, orchestrator_assessor
from app.services.lesson_service import LessonService
from app.services.session_service import SessionService


def _build_lesson_service(store: SessionStore, settings: Settings) -> LessonService:
    """Default lesson service: Strands specialists behind the resilient model client."""
    client = create_model_client(settings)
    orchestrator = Orchestrator(
        environment=EnvironmentSpecialist(client),
        curriculum=CurriculumSpecialist(client),
        storytelling=StorytellingSpecialist(client),
        assessment=AssessmentSpecialist(client),
        settings=settings,
    )
    return LessonService(store, orchestrator, settings)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    client_identifier: ClientIdentifier | None = None,
    readiness_probes: health.ReadinessProbes | None = None,
    session_store: SessionStore | None = None,
    session_service: SessionService | None = None,
    lesson_service: LessonService | None = None,
    learning_service: LearningLoopService | None = None,
    demo_service: DemoService | None = None,
) -> FastAPI:
    """Build the FastAPI app with injected settings and dependencies.

    Args:
        settings: Runtime settings; defaults to the process-wide settings.
        clock: Time source for the rate-limit window (injectable for deterministic tests).
        client_identifier: Maps an ASGI scope to a client id for per-client rate limiting.
        readiness_probes: Dependency-health probes for ``/readyz`` (R-11.6). Defaults to an
            empty map, meaning no external dependency is required to be ready.
        session_store: Session_Store backend. Defaults to an in-memory store sized to the
            configured TTL (R-10.7). Ignored when ``session_service`` is supplied.
        session_service: Pre-built :class:`SessionService` (injects store/clock/token
            generators for deterministic tests). When omitted, one is built over
            ``session_store`` with the configured TTL.
    """
    resolved_settings = settings or get_settings()
    app = FastAPI(title="The Invisible Classroom", version="0.1.0")
    app.state.settings = resolved_settings
    app.state.readiness_probes = dict(readiness_probes or {})

    # Session_Store and lifecycle service wired onto app.state so routes and the capability-token
    # dependency share one instance (design: dependency injection for store/clock). TTL comes
    # from configuration (R-10.7); an in-memory store is the default for local/dev.
    ttl = timedelta(hours=resolved_settings.session_ttl_hours)
    resolved_store = session_store or InMemorySessionStore(ttl=ttl)
    resolved_service = session_service or SessionService(resolved_store, ttl=ttl)
    app.state.session_service = resolved_service
    resolved_lessons = lesson_service or _build_lesson_service(resolved_store, resolved_settings)
    app.state.lesson_service = resolved_lessons
    # Learning loop shares the lesson service's orchestrator for the Assessment_Specialist.
    app.state.learning_service = learning_service or LearningLoopService(
        resolved_store,
        AssessmentService(orchestrator_assessor(resolved_lessons.orchestrator, resolved_settings)),
        resolved_settings,
    )

    # Demo_Mode reuses the session service, store and the lesson service's orchestrator.
    app.state.demo_service = demo_service or DemoService(
        resolved_service, resolved_store, resolved_lessons.orchestrator, resolved_settings
    )

    # Error handlers first so middleware-raised and handler-raised errors both render as
    # ApiError bodies. (Registration order does not affect dispatch.)
    install_error_handlers(app)

    # Health routes: liveness makes no external calls (R-11.5); readiness uses the injected
    # probes (R-11.6).
    app.include_router(health.router)
    # Session routes (prefix /api/v1): creation is public; the rest require a capability token.
    app.include_router(sessions.router)
    app.include_router(lessons.router)
    app.include_router(learning.router)
    app.include_router(demo.router)

    # Pure-ASGI request-limit middleware wraps the whole app so limits are enforced before
    # routing — rejections never reach a handler and never write to the store (R-11.4).
    # Fall back to the middleware's own defaults when a dependency is not injected.
    app.add_middleware(
        RequestLimitMiddleware,
        settings=resolved_settings,
        clock=clock or default_clock,
        client_identifier=client_identifier or default_client_identifier,
    )

    return app
