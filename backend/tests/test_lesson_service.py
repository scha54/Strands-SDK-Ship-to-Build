"""Lesson service, Safe_Templates and lesson/event routes (task 6.8).

Covers R-03.1, R-03.4, R-03.5, R-04.5, R-11.1, R-11.2; NFR-05, NFR-10.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from app.adapters.bedrock import ResilientModelClient, StubModel
from app.adapters.session_store import InMemorySessionStore
from app.agents.assessment import AssessmentSpecialist
from app.agents.budget import RequestBudget
from app.agents.curriculum import CurriculumSpecialist
from app.agents.environment import EnvironmentSpecialist
from app.agents.orchestrator import CancelToken, LessonRequest, Orchestrator
from app.agents.stage_events import StageEmitter
from app.agents.storytelling import StorytellingSpecialist
from app.config import Settings
from app.domain.models import AgeBand, CreateSessionRequest, Lesson, Subject
from app.domain.state_machine import InvalidStateTransition
from app.main import create_app
from app.services.gates import check_lesson
from app.services.idempotency import IdempotencyKeyConflict
from app.services.lesson_service import GenerationCapReached, LessonService
from app.services.normalizer import normalize_objects
from app.services.safe_templates import (
    SAFE_TEMPLATE_LABEL,
    available_templates,
    build_safe_template,
)
from app.services.session_service import SessionService
from fastapi.testclient import TestClient

UNSAFE_STORY: dict[str, Any] = {
    "contract_version": "1.0",
    "title": "Bad story",
    "setup": "Gather your objects.",
    "activities": [
        {
            "id": f"a{i}",
            "instruction": "Count the stone items. How many are there?",
            "facilitator_note": "Cut the paper with a knife.",
            "required_objects": ["stone"],
            "answer_kind": "integer",
            "expected_answer": "3",
            "rubric": "Counts correctly.",
            "hints": ["Count slowly."],
            "difficulty": 1,
        }
        for i in range(3)
    ],
}


async def _no_sleep(_: float) -> None:
    return None


class CountingOrchestrator(Orchestrator):
    """Real orchestrator that counts generate_lesson calls."""

    calls = 0

    async def generate_lesson(
        self,
        req: LessonRequest,
        budget: RequestBudget,
        emit: StageEmitter,
        cancel: CancelToken | None = None,
    ) -> Lesson:
        self.calls += 1
        return await super().generate_lesson(req, budget, emit, cancel)


class HangingOrchestrator(CountingOrchestrator):
    """Never answers; records that the pending call was cancelled."""

    cancelled = False

    async def generate_lesson(
        self,
        req: LessonRequest,
        budget: RequestBudget,
        emit: StageEmitter,
        cancel: CancelToken | None = None,
    ) -> Lesson:
        self.calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


def _orchestrator(
    stub: StubModel | None = None, cls: type[CountingOrchestrator] = CountingOrchestrator
) -> CountingOrchestrator:
    settings = Settings(model_retry_backoff_seconds=0, specialist_retries=0)
    client = ResilientModelClient(stub or StubModel(), settings, sleep=_no_sleep)
    return cls(
        environment=EnvironmentSpecialist(client),
        curriculum=CurriculumSpecialist(client),
        storytelling=StorytellingSpecialist(client),
        assessment=AssessmentSpecialist(client),
        settings=settings,
    )


def _setup(
    orch: CountingOrchestrator | None = None,
    objects: list[str] | None = None,
    **settings_kw: Any,
) -> tuple[LessonService, SessionService, InMemorySessionStore, str, CountingOrchestrator]:
    settings = Settings(**settings_kw)
    store = InMemorySessionStore()
    sessions = SessionService(store)
    orch = orch or _orchestrator()
    svc = LessonService(store, orch, settings)
    created = sessions.create(
        CreateSessionRequest(
            age_band=AgeBand.B6_8,
            subject=Subject.ARITHMETIC,
            objects=objects or ["Stone", "leaf"],
        )
    )
    return svc, sessions, store, created.session_id, orch


async def _run(svc: LessonService, sid: str, key: str = "k1") -> Any:
    svc.start(sid, key)
    return await svc.run(sid)


async def test_success_persists_generated_lesson_and_events() -> None:
    """R-03.1, R-04.5, R-11.1: gated Lesson is stored, state READY, stage events kept."""
    svc, sessions, _, sid, orch = _setup()
    out = await _run(svc, sid)
    rec = sessions.get(sid)
    assert out.status == "ready" and out.source == "generated"
    assert orch.calls == 1
    assert rec.state == "ready" and rec.lesson is not None and rec.lesson.source == "generated"
    assert [e.status for e in rec.stage_events].count("completed") == 3


async def test_gate_failure_makes_at_most_three_attempts_then_labeled_template() -> None:
    """R-03.4, R-03.5, NFR-10: 1 + 2 retries, then the labeled Safe_Template is stored."""
    orch = _orchestrator(StubModel(overrides={"StoryDraft": UNSAFE_STORY}))
    svc, sessions, _, sid, _ = _setup(orch)
    out = await _run(svc, sid)
    assert orch.calls == 3
    assert out.attempts == 3
    assert out.status == "ready" and out.source == "safe_template"
    assert out.label == SAFE_TEMPLATE_LABEL
    assert any("hazard" in r for r in out.gate_reasons)
    rec = sessions.get(sid)
    assert rec.state == "ready" and rec.lesson is not None
    assert rec.lesson.source == "safe_template"
    assert rec.lesson.setup.startswith(SAFE_TEMPLATE_LABEL)


async def test_no_template_means_failure_and_no_lesson_stored() -> None:
    """R-03.5: exhausted attempts without a template fail and persist no Lesson."""
    orch = _orchestrator(StubModel(overrides={"StoryDraft": UNSAFE_STORY}))
    settings = Settings()
    store = InMemorySessionStore()
    svc = LessonService(store, orch, settings, template_builder=lambda a, s, o: None)
    sessions = SessionService(store)
    sid = sessions.create(
        CreateSessionRequest(age_band=AgeBand.B6_8, subject=Subject.ARITHMETIC, objects=["stone"])
    ).session_id
    out = await _run(svc, sid)
    assert orch.calls == 3
    assert out.status == "failed" and out.error_code == "gates_failed"
    rec = sessions.get(sid)
    assert rec.state == "failed" and rec.lesson is None
    assert [o.original for o in rec.objects] == ["stone"]


async def test_timeout_returns_within_two_seconds_with_both_options() -> None:
    """R-03.5, NFR-05: a hung model call is cancelled; retry and Safe_Template are offered."""
    orch = _orchestrator(cls=HangingOrchestrator)
    svc, sessions, _, sid, _ = _setup(orch, generation_deadline_seconds=0.05)
    start = time.monotonic()
    out = await _run(svc, sid)
    assert time.monotonic() - start < 2
    assert out.status == "failed" and out.error_code == "model_timeout"
    assert set(out.options) == {"retry", "safe_template"}
    assert isinstance(orch, HangingOrchestrator) and orch.cancelled
    rec = sessions.get(sid)
    assert rec.state == "failed" and rec.lesson is None
    assert [o.original for o in rec.objects] == ["Stone", "leaf"]  # inputs kept


async def test_model_error_offers_retry_and_template_then_template_mode_works() -> None:
    """R-03.5: a model error fails with both options; the template can then be chosen."""
    orch = _orchestrator(StubModel(failures=None))
    svc, sessions, _, sid, _ = _setup(orch)
    out = await _run(svc, sid)
    assert out.status == "failed" and set(out.options) == {"retry", "safe_template"}
    svc.start(sid, "k2", "safe_template")
    out2 = await svc.run(sid, "safe_template")
    assert out2.status == "ready" and out2.source == "safe_template"
    assert sessions.get(sid).state == "ready"


async def test_repeated_idempotency_key_does_not_regenerate() -> None:
    """R-11.2, NFR-05: same key and payload replays; a different payload conflicts."""
    svc, _, _, sid, orch = _setup()
    first = svc.start(sid, "same")
    await svc.run(sid)
    again = svc.start(sid, "same")
    assert not first.replayed and again.replayed
    assert orch.calls == 1
    with pytest.raises(IdempotencyKeyConflict):
        svc.start(sid, "same", "safe_template")


async def test_generation_cap_and_state_guard() -> None:
    """R-11.1: the per-session cap rejects extra generations; READY cannot regenerate."""
    svc, _, _, sid, _ = _setup(
        _orchestrator(StubModel(failures=None)), max_generations_per_session=1
    )
    await _run(svc, sid, "a")
    with pytest.raises(GenerationCapReached):
        svc.start(sid, "b")
    svc2, _, _, sid2, _ = _setup()
    await _run(svc2, sid2, "a")
    with pytest.raises(InvalidStateTransition):
        svc2.start(sid2, "b")


@pytest.mark.parametrize(("age", "subject"), [(a, s) for a in AgeBand for s in Subject])
def test_safe_template_exists_and_passes_gates_for_every_band_and_subject(
    age: AgeBand, subject: Subject
) -> None:
    """R-03.5, NFR-10: curated templates exist for all pairs and pass every gate."""
    assert (age, subject) in available_templates()
    for obj in ("stone", "Bottle cap", "leaf"):
        lesson = build_safe_template(age, subject, obj)
        assert lesson is not None and lesson.source == "safe_template"
        result = check_lesson(lesson, normalize_objects([obj]), age, subject)
        assert result.passed, result.reasons
        lesson.check_inputs([obj])


# --- Routes -------------------------------------------------------------------------------------


def _client(
    orch: CountingOrchestrator | None = None, **kw: Any
) -> tuple[TestClient, Any, dict[str, str]]:
    svc, sessions, store, sid, orch = _setup(orch, **kw)
    app = create_app(Settings(**kw), session_service=sessions, lesson_service=svc)
    client = TestClient(app)
    # Re-create through the API so a capability token is available.
    resp = client.post(
        "/api/v1/sessions",
        json={"age_band": "6-8", "subject": "arithmetic_counting", "objects": ["Stone", "leaf"]},
    )
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['capability_token']}"}
    return client, (body["session_id"], orch, sessions), headers


def test_post_lessons_returns_202_is_idempotent_and_events_are_listed() -> None:
    """R-11.1, R-11.2, R-04.5: 202, one generation for a repeated key, sanitized events."""
    client, (sid, orch, _), h = _client()
    url = f"/api/v1/sessions/{sid}/lessons"
    r1 = client.post(url, headers={**h, "Idempotency-Key": "k"})
    r2 = client.post(url, headers={**h, "Idempotency-Key": "k"})
    assert r1.status_code == 202 and r1.json()["replayed"] is False
    assert r2.status_code == 202 and r2.json()["replayed"] is True
    assert orch.calls == 1
    ev = client.get(f"/api/v1/sessions/{sid}/events", headers=h).json()
    assert ev["state"] == "ready" and ev["lesson_source"] == "generated"
    assert {e["specialist"] for e in ev["events"]} == {"environment", "curriculum", "storytelling"}
    assert all(
        set(e) <= {"stage", "specialist", "status", "contract_version", "timestamp"}
        for e in ev["events"]
    )


def test_post_lessons_requires_key_conflicts_and_blocks_after_stop() -> None:
    """R-11.2, R-08.3: missing key is 422, key reuse with a new payload 409, Stop blocks."""
    client, (sid, _, _), h = _client()
    url = f"/api/v1/sessions/{sid}/lessons"
    assert client.post(url, headers=h).status_code == 422
    assert client.post(url, headers={**h, "Idempotency-Key": "k"}).status_code == 202
    conflict = client.post(
        url, headers={**h, "Idempotency-Key": "k"}, json={"mode": "safe_template"}
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_key_conflict"
    client.post(f"/api/v1/sessions/{sid}/stop", headers=h)
    stopped = client.post(url, headers={**h, "Idempotency-Key": "z"})
    assert stopped.status_code == 409 and stopped.json()["code"] == "session_stopped"


def test_failed_generation_reports_options_through_events() -> None:
    """R-03.5: a failed generation shows retry and Safe_Template options; no Lesson stored."""
    client, (sid, _, sessions), h = _client(_orchestrator(StubModel(failures=None)))
    client.post(f"/api/v1/sessions/{sid}/lessons", headers={**h, "Idempotency-Key": "k"})
    ev = client.get(f"/api/v1/sessions/{sid}/events", headers=h).json()
    assert ev["state"] == "failed" and set(ev["options"]) == {"retry", "safe_template"}
    assert sessions.get(sid).lesson is None
