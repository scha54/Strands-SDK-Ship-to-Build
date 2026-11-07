"""Demo_Mode, seed data and Demo_Fallback (task 10.1).

Covers R-12.1, R-12.2, R-12.4, R-12.6; NFR-05, NFR-09.
Timeouts are injected (no real 10 s wait) and the live model is a deterministic stub.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from typing import Any

from app.adapters.bedrock import RawResponse, ResilientModelClient, StubModel
from app.adapters.session_store import InMemorySessionStore
from app.agents.assessment import AssessmentSpecialist
from app.agents.curriculum import CurriculumSpecialist
from app.agents.environment import EnvironmentSpecialist
from app.agents.orchestrator import Orchestrator
from app.agents.storytelling import StorytellingSpecialist
from app.config import Settings
from app.domain.models import AgeBand, ObjectInventory, Subject
from app.main import create_app
from app.services.demo_seed import DEMO_FALLBACK_LABEL, STAGE_ORDER, load_demo_seed
from app.services.demo_service import DemoService, map_stages
from app.services.gates import check_lesson
from app.services.normalizer import normalize_objects
from app.services.session_service import SessionService
from fastapi.testclient import TestClient
from pydantic import BaseModel


async def _no_sleep(_: float) -> None:
    return None


class HangingModel:
    """Raw model that never answers (Bedrock silent)."""

    async def invoke(self, *, system: str, prompt: str, schema: type[BaseModel]) -> RawResponse:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _orchestrator(raw: Any, settings: Settings) -> Orchestrator:
    client = ResilientModelClient(raw, settings, sleep=_no_sleep)
    return Orchestrator(
        environment=EnvironmentSpecialist(client),
        curriculum=CurriculumSpecialist(client),
        storytelling=StorytellingSpecialist(client),
        assessment=AssessmentSpecialist(client),
        settings=settings,
    )


def _service(raw: Any, runner: Any = None) -> tuple[DemoService, InMemorySessionStore, list[float]]:
    settings = Settings(model_retry_backoff_seconds=0, specialist_retries=0)
    store = InMemorySessionStore()
    seen: list[float] = []

    async def default_runner(coro: Coroutine[Any, Any, Any], timeout: float) -> Any:
        seen.append(timeout)
        return await coro

    service = DemoService(
        SessionService(store),
        store,
        _orchestrator(raw, settings),
        settings,
        timeout_runner=runner or default_runner,
    )
    return service, store, seen


async def _expire(coro: Coroutine[Any, Any, Any], timeout: float) -> Any:
    """Injected deadline: start the call, then time out at once instead of waiting."""
    _EXPIRED.append(timeout)
    task = asyncio.ensure_future(coro)
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    raise TimeoutError


_EXPIRED: list[float] = []


def test_seed_is_the_preset() -> None:
    """R-12.1: Age_Band 6-8, mathematics, exactly seven Objects (five stones, two leaves)."""
    seed = load_demo_seed()
    assert seed.age_band is AgeBand.B6_8
    assert seed.subject is Subject.ARITHMETIC and seed.subject_label == "mathematics"
    assert len(seed.objects) == 7
    assert sum(o.startswith("Stone") for o in seed.objects) == 5
    assert sum(o.startswith("Leaf") for o in seed.objects) == 2
    assert tuple(s.stage for s in seed.stages) == STAGE_ORDER


def test_seed_lesson_passes_validation_gates() -> None:
    """R-12.4, NFR-09: the pre-recorded Lesson is grounded and safe; no efficacy claims."""
    seed = load_demo_seed()
    inventory = normalize_objects(list(seed.objects))
    result = check_lesson(seed.lesson, inventory, seed.age_band, seed.subject)
    assert result.passed, result.reasons
    assert seed.lesson.source == "demo_fallback"


async def test_create_session_loads_preset_without_input_or_model_call() -> None:
    """R-12.1: preset Session with a seven-Object inventory and zero model calls."""
    stub = StubModel()
    service, store, _ = _service(stub)
    created = service.create_session()
    record = store.get(created.session_id, created.record.updated_at)
    assert record.age_band is AgeBand.B6_8 and record.subject is Subject.ARITHMETIC
    assert len(ObjectInventory(items=record.objects).items) == 7
    assert record.state == "generating"
    assert stub.calls == 0


async def test_live_run_completes_within_three_seconds_with_stub() -> None:
    """R-12.1, R-12.2: stubbed live run finishes in 3 s with all five stages complete."""
    service, store, seen = _service(StubModel())
    start = time.monotonic()
    created = service.create_session()
    outcome = await service.run(created.session_id)
    assert time.monotonic() - start < 3
    assert outcome.status == "ready" and outcome.source == "generated" and outcome.label is None
    assert [s.state for s in outcome.stages] == ["complete"] * 5
    assert seen == [10.0]  # the 10 s Demo_Fallback trigger is applied
    assert store.get(created.session_id, created.record.updated_at).state == "ready"


async def test_fallback_after_injected_timeout_completes_five_stages_in_order() -> None:
    """R-12.4: a silent Bedrock hits the 10 s trigger; seed plays all five stages, labeled."""
    _EXPIRED.clear()
    service, store, _ = _service(HangingModel(), runner=_expire)
    created = service.create_session()
    outcome = await service.run(created.session_id)
    assert _EXPIRED == [10.0]
    assert outcome.source == "demo_fallback" and outcome.label == DEMO_FALLBACK_LABEL
    assert DEMO_FALLBACK_LABEL == "Demo fallback — no live agent execution"
    assert [s.stage for s in outcome.stages] == list(STAGE_ORDER)
    assert [s.state for s in outcome.stages] == ["complete"] * 5
    record = store.get(created.session_id, created.record.updated_at)
    assert record.state == "ready" and record.lesson is not None
    assert record.lesson.source == "demo_fallback"
    assert record.lesson.objects and len(record.stage_events) == 10


async def test_fallback_when_bedrock_unavailable() -> None:
    """R-12.4: an unavailable model also triggers the labeled Demo_Fallback."""
    service, _, _ = _service(StubModel(failures=None))
    outcome = await service.run(service.create_session().session_id)
    assert outcome.source == "demo_fallback" and outcome.label == DEMO_FALLBACK_LABEL
    assert [s.state for s in outcome.stages] == ["complete"] * 5


async def test_stage_order_identical_across_two_runs() -> None:
    """R-12.6, NFR-05: same seed inputs give the same stage order on every run."""
    runs: list[list[tuple[str, str]]] = []
    for _ in range(2):
        service, store, _ = _service(HangingModel(), runner=_expire)
        created = service.create_session()
        await service.run(created.session_id)
        record = store.get(created.session_id, created.record.updated_at)
        runs.append([(e.stage, e.status) for e in record.stage_events])
    assert runs[0] == runs[1]
    assert [s for s, st in runs[0] if st == "started"] == list(STAGE_ORDER)


def test_map_stages_pending_in_progress_complete() -> None:
    """R-12.2: events map onto the five stages as pending, in progress or complete."""
    from app.agents.stage_events import StageEventLog

    log = StageEventLog()
    log("understand_objects", "environment", "started")
    log("understand_objects", "environment", "completed", "1.0")
    log("choose_objective", "curriculum", "started")
    states = {s.stage: s.state for s in map_stages(log.events)}
    assert states == {
        "understand_objects": "complete",
        "choose_objective": "in_progress",
        "create_story": "pending",
        "assess_answer": "pending",
        "adapt_next_activity": "pending",
    }


def test_demo_route_creates_session_and_reports_fallback_label() -> None:
    """R-12.1, R-12.4: POST /demo/session needs no input; events show the label in fallback."""
    settings = Settings(use_stub_model=False, model_retry_backoff_seconds=0, specialist_retries=0)
    store = InMemorySessionStore()
    sessions = SessionService(store)
    demo = DemoService(sessions, store, _orchestrator(StubModel(failures=None), settings), settings)
    client = TestClient(
        create_app(settings, session_store=store, session_service=sessions, demo_service=demo)
    )
    start = time.monotonic()
    response = client.post("/api/v1/demo/session")
    assert time.monotonic() - start < 3
    assert response.status_code == 201
    body = response.json()
    assert body["age_band"] == "6-8" and body["subject_label"] == "mathematics"
    assert len(body["objects"]) == 7
    assert [s["state"] for s in body["stages"]] == ["pending"] * 5
    headers = {"Authorization": f"Bearer {body['capability_token']}"}
    events = client.get(body["events_url"], headers=headers).json()
    assert events["lesson_source"] == "demo_fallback"
    assert events["label"] == DEMO_FALLBACK_LABEL
    assert events["state"] == "ready"
