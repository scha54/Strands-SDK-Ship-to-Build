"""Orchestrator (R-04.1, R-04.2, R-04.3, R-04.5, R-04.6, R-04.7, R-08.3; NFR-05, NFR-10)."""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

import pytest
from app.adapters.bedrock import ModelUnavailable, ResilientModelClient, StubModel
from app.adapters.session_store import InMemorySessionStore
from app.agents.assessment import AssessmentSpecialist
from app.agents.budget import RequestBudget
from app.agents.curriculum import CurriculumSpecialist
from app.agents.environment import EnvironmentSpecialist
from app.agents.orchestrator import (
    AssessRequest,
    Cancelled,
    CancelToken,
    LessonRequest,
    LimitExceeded,
    Orchestrator,
    SpecialistFailed,
)
from app.agents.stage_events import StageEventLog
from app.agents.storytelling import StorytellingSpecialist
from app.config import Settings
from app.domain.models import AgeBand, AssessmentStatus, Subject
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
REQ = LessonRequest(age_band=AgeBand.B6_8, subject=Subject.ARITHMETIC, objects=["Stone", "leaf"])


async def _no_sleep(_: float) -> None:
    return None


class RecordingClient:
    """Wraps a real client and records which contract each call asked for."""

    def __init__(self, inner: ResilientModelClient) -> None:
        self.inner = inner
        self.schemas: list[str] = []

    async def generate(self, *, system: str, prompt: str, schema: type[T], budget: Any) -> T:
        self.schemas.append(schema.__name__)
        return await self.inner.generate(system=system, prompt=prompt, schema=schema, budget=budget)


def _build(
    stub: StubModel | None = None, **settings_kw: Any
) -> tuple[Orchestrator, RecordingClient, Settings]:
    settings = Settings(model_retry_backoff_seconds=0, specialist_retries=2, **settings_kw)
    # Client-level retries off so every retry seen is the orchestrator's.
    client_settings = Settings(model_retry_backoff_seconds=0, specialist_retries=0)
    client = RecordingClient(
        ResilientModelClient(stub or StubModel(), client_settings, sleep=_no_sleep)
    )
    orch = Orchestrator(
        environment=EnvironmentSpecialist(client),
        curriculum=CurriculumSpecialist(client),
        storytelling=StorytellingSpecialist(client),
        assessment=AssessmentSpecialist(client),
        settings=settings,
    )
    return orch, client, settings


async def test_generate_lesson_invokes_specialists_in_order() -> None:
    """R-04.1, R-04.2, R-04.5: Environment, Curriculum, Storytelling, once each, in order."""
    orch, client, settings = _build()
    log = StageEventLog()
    lesson = await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log)
    assert client.schemas == ["EnvironmentOutput", "CurriculumPlan", "StoryDraft"]
    assert lesson.source == "generated"
    assert len(lesson.activities) == 3
    assert [(e.specialist, e.status) for e in log.events] == [
        ("environment", "started"),
        ("environment", "completed"),
        ("curriculum", "started"),
        ("curriculum", "completed"),
        ("storytelling", "started"),
        ("storytelling", "completed"),
    ]


async def test_stage_events_record_contract_version() -> None:
    """R-04.3, R-04.5: completed events carry the contract version, started ones do not."""
    orch, _, settings = _build()
    log = StageEventLog()
    await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log)
    assert all(e.contract_version == "1.0" for e in log.events if e.status == "completed")
    assert all(e.contract_version is None for e in log.events if e.status == "started")


async def test_assess_invokes_assessment_specialist() -> None:
    """R-04.1, R-04.2: assess calls the Assessment_Specialist exactly once."""
    orch, client, settings = _build()
    log = StageEventLog()
    lesson = await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log)
    client.schemas.clear()
    out = await orch.assess(
        AssessRequest(activity=lesson.activities[0], answer="2"),
        RequestBudget.for_assessment(settings),
        log,
    )
    assert client.schemas == ["AssessmentOutput"]
    assert out.status is AssessmentStatus.CORRECT
    assert log.events[-1].specialist == "assessment"
    assert log.events[-1].status == "completed"


async def test_failing_specialist_retried_then_named_error_and_empty_store() -> None:
    """R-04.3, R-04.6, NFR-05: 1 + 2 retries, error names the specialist, nothing persisted."""
    store = InMemorySessionStore()
    stub = StubModel(malformed=True)
    orch, client, settings = _build(stub)
    log = StageEventLog()
    with pytest.raises(SpecialistFailed) as exc:
        await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log)
    assert exc.value.specialist == "environment"
    assert "environment" in str(exc.value)
    assert stub.calls == 3  # initial attempt + retry limit of 2
    assert client.schemas == ["EnvironmentOutput"] * 3
    assert store._items == {}
    assert [(e.specialist, e.status) for e in log.events] == [
        ("environment", "started"),
        ("environment", "failed"),
    ]


async def test_transient_failure_recovers_within_retry_limit() -> None:
    """R-04.6: a specialist that fails twice then succeeds does not fail the request."""
    stub = StubModel(failures=2)
    orch, client, settings = _build(stub)
    await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), StageEventLog())
    assert client.schemas.count("EnvironmentOutput") == 3
    assert client.schemas[-2:] == ["CurriculumPlan", "StoryDraft"]


async def test_contract_version_mismatch_is_invalid_output() -> None:
    """R-04.3: an output with the wrong contract version is rejected and retried."""
    stub = StubModel(
        overrides={
            "EnvironmentOutput": {
                "contract_version": "9.9",
                "inventory": {"items": [{"original": "a", "normalized": "a"}]},
            }
        }
    )
    orch, _, settings = _build(stub)
    with pytest.raises(SpecialistFailed) as exc:
        await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), StageEventLog())
    assert exc.value.specialist == "environment"
    assert stub.calls == 3


async def test_limit_reached_stops_with_failed_event_and_named_limit() -> None:
    """R-04.7, NFR-05: LimitReached stops the run, emits failed, names the limit."""
    orch, client, settings = _build(max_specialist_calls=2)
    log = StageEventLog()
    with pytest.raises(LimitExceeded) as exc:
        await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log)
    assert exc.value.limit_name == "calls"
    assert "calls" in str(exc.value)
    assert client.schemas == ["EnvironmentOutput", "CurriculumPlan"]
    assert (log.events[-1].specialist, log.events[-1].status) == ("storytelling", "failed")


async def test_each_stage_has_one_start_and_one_terminal_event() -> None:
    """R-04.5: a started event followed by exactly one completed or failed event."""
    orch, _, settings = _build(StubModel(failures=None))
    log = StageEventLog()
    with pytest.raises(SpecialistFailed):
        await orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log)
    assert [e.status for e in log.events] == ["started", "failed"]


class HangingClient:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def generate(self, *, system: str, prompt: str, schema: type[T], budget: Any) -> T:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise ModelUnavailable("unreachable")


async def test_stop_cancels_pending_model_call() -> None:
    """R-08.3, NFR-05: setting the cancel token cancels the in-flight call."""
    settings = Settings()
    client = HangingClient()
    orch = Orchestrator(
        environment=EnvironmentSpecialist(client),
        curriculum=CurriculumSpecialist(client),
        storytelling=StorytellingSpecialist(client),
        assessment=AssessmentSpecialist(client),
        settings=settings,
    )
    token = CancelToken()
    log = StageEventLog()
    task = asyncio.create_task(
        orch.generate_lesson(REQ, RequestBudget.for_generation(settings), log, token)
    )
    await asyncio.wait_for(client.started.wait(), 1)
    token.set()
    with pytest.raises(Cancelled):
        await asyncio.wait_for(task, 1)
    assert client.cancelled
    assert log.events[-1].status == "failed"


async def test_already_stopped_makes_no_model_call() -> None:
    """R-08.3: a request started after Stop never calls the model."""
    orch, client, settings = _build()
    token = CancelToken()
    token.set()
    with pytest.raises(Cancelled):
        await orch.generate_lesson(
            REQ, RequestBudget.for_generation(settings), StageEventLog(), token
        )
    assert client.schemas == []
