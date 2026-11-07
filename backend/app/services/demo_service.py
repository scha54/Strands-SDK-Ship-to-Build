"""Demo_Mode service: preset session, five-stage run and Demo_Fallback.

Covers R-12.1, R-12.2, R-12.4, R-12.6; NFR-05, NFR-09.

* :meth:`DemoService.create_session` loads the seed preset through the normal
  :class:`SessionService` with no user input or image and no model call (R-12.1), then reserves
  the Session (``GENERATING``).
* :meth:`DemoService.run` tries the live agents through the Orchestrator (understand objects,
  choose objective, create story, assess answer) plus the adapt step. If Bedrock is unavailable,
  the output fails the gates, or nothing completes within ``demo_fallback_trigger_seconds``
  (10 s), it plays the pre-recorded seed through the same five stages with
  ``source="demo_fallback"`` (R-12.4). The deadline runner is injectable so tests never wait.
* :func:`map_stages` maps Stage_Events onto the five ordered stages (R-12.2). Fallback events are
  generated in seed order, so stage order is identical on every run (R-12.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal

from app.adapters.bedrock import ModelError
from app.adapters.session_store import Clock, SessionStore, SystemClock, VersionConflict
from app.agents.budget import RequestBudget
from app.agents.orchestrator import (
    AssessRequest,
    LessonRequest,
    OrchestrationError,
    Orchestrator,
)
from app.agents.stage_events import StageEventLog
from app.config import Settings
from app.domain.models import (
    AgentStageEvent,
    Assessment,
    CreateSessionRequest,
    Lesson,
    ObjectInventory,
)
from app.domain.state_machine import SessionState, validate_transition
from app.services.demo_seed import (
    DEMO_FALLBACK_LABEL,
    STAGE_ORDER,
    STAGE_TITLES,
    DemoSeed,
    load_demo_seed,
)
from app.services.gates import check_lesson
from app.services.session_service import CreatedSession, SessionService

STAGE_ADAPT = "adapt_next_activity"
ADAPT_SPECIALIST = "orchestrator"

StageState = Literal["pending", "in_progress", "complete"]
# Runs a coroutine under a deadline; raises TimeoutError when it expires. Injectable for tests.
TimeoutRunner = Callable[[Coroutine[Any, Any, Any], float], Coroutine[Any, Any, Any]]


async def _wait_for(coro: Coroutine[Any, Any, Any], timeout: float) -> Any:
    return await asyncio.wait_for(coro, timeout=timeout)


@dataclass(frozen=True)
class DemoStage:
    """One of the five timeline stages and its state (R-12.2)."""

    stage: str
    title: str
    state: StageState


@dataclass(frozen=True)
class DemoOutcome:
    """Result of :meth:`DemoService.run`."""

    status: Literal["ready", "stopped"]
    source: Literal["generated", "demo_fallback"] | None = None
    label: str | None = None
    lesson: Lesson | None = None
    assessment: Assessment | None = None
    stages: tuple[DemoStage, ...] = ()


class _LiveRejected(Exception):  # noqa: N818
    """Live output failed the Validation_Gates; use the fallback instead."""


def map_stages(events: list[AgentStageEvent]) -> list[DemoStage]:
    """Map Stage_Events onto the five ordered stages: pending, in progress or complete."""
    result: list[DemoStage] = []
    for stage in STAGE_ORDER:
        statuses = [e.status for e in events if e.stage == stage]
        state: StageState = "pending"
        if "completed" in statuses:
            state = "complete"
        elif statuses and statuses[-1] == "started":
            state = "in_progress"
        result.append(DemoStage(stage=stage, title=STAGE_TITLES[stage], state=state))
    return result


class DemoService:
    def __init__(
        self,
        sessions: SessionService,
        store: SessionStore,
        orchestrator: Orchestrator,
        settings: Settings,
        *,
        clock: Clock | None = None,
        timeout_runner: TimeoutRunner = _wait_for,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._orchestrator = orchestrator
        self._settings = settings
        self._clock: Clock = clock or SystemClock()
        self._run_with_timeout = timeout_runner

    @property
    def seed(self) -> DemoSeed:
        return load_demo_seed()

    def create_session(self) -> CreatedSession:
        """Load the preset Session from the seed and reserve it for the run (R-12.1)."""
        seed = self.seed
        created = self._sessions.create(
            CreateSessionRequest(
                age_band=seed.age_band, subject=seed.subject, objects=list(seed.objects)
            )
        )
        record = created.record
        validate_transition(SessionState.CREATED, SessionState.GENERATING)
        now = self._clock.now()
        self._store.put_if_version(
            record.model_copy(update={"state": SessionState.GENERATING.value, "updated_at": now}),
            record.version,
        )
        return CreatedSession(
            session_id=created.session_id,
            capability_token=created.capability_token,
            record=self._store.get(created.session_id, now),
        )

    async def run(self, session_id: str) -> DemoOutcome:
        """Run the five stages live, or play the seed as Demo_Fallback (R-12.2, R-12.4)."""
        record = self._store.get(session_id, self._clock.now())
        if record.state != SessionState.GENERATING.value:
            return DemoOutcome(status="stopped")
        seed = self.seed
        log = StageEventLog(self._clock.now)
        try:
            lesson, assessment = await self._run_with_timeout(
                self._live(record.objects, seed, log),
                self._settings.demo_fallback_trigger_seconds,
            )
            source: Literal["generated", "demo_fallback"] = "generated"
        except (TimeoutError, OrchestrationError, ModelError, _LiveRejected):
            log = StageEventLog(self._clock.now)  # discard partial live events
            lesson, assessment = self._play_fallback(seed, log)
            source = "demo_fallback"
        events = log.events
        if not self._persist(session_id, lesson, events):
            return DemoOutcome(status="stopped")
        return DemoOutcome(
            status="ready",
            source=source,
            label=DEMO_FALLBACK_LABEL if source == "demo_fallback" else None,
            lesson=lesson,
            assessment=assessment,
            stages=tuple(map_stages(events)),
        )

    # -- live and fallback paths -------------------------------------------------------------

    async def _live(
        self, items: list[Any], seed: DemoSeed, log: StageEventLog
    ) -> tuple[Lesson, Assessment]:
        names = [i.original for i in items]
        request = LessonRequest(age_band=seed.age_band, subject=seed.subject, objects=names)
        lesson = await self._orchestrator.generate_lesson(
            request, RequestBudget.for_generation(self._settings), log
        )
        gate = check_lesson(lesson, ObjectInventory(items=items), seed.age_band, seed.subject)
        if not gate.passed:
            raise _LiveRejected
        assessment = await self._orchestrator.assess(
            AssessRequest(activity=lesson.activities[0], answer=seed.scripted_answer.answer),
            RequestBudget.for_assessment(self._settings),
            log,
        )
        log(STAGE_ADAPT, ADAPT_SPECIALIST, "started")
        log(STAGE_ADAPT, ADAPT_SPECIALIST, "completed")
        return lesson, assessment

    @staticmethod
    def _play_fallback(seed: DemoSeed, log: StageEventLog) -> tuple[Lesson, Assessment]:
        """Emit the pre-recorded stages in seed order, each started then completed."""
        for stage in seed.stages:
            log(stage.stage, stage.specialist, "started")
            log(stage.stage, stage.specialist, "completed", stage.contract_version)
        return seed.lesson.model_copy(update={"source": "demo_fallback"}), seed.assessment

    # -- persistence -------------------------------------------------------------------------

    def _persist(self, session_id: str, lesson: Lesson, events: list[AgentStageEvent]) -> bool:
        """Conditional write GENERATING -> READY; never overwrite a Stop (R-08.3)."""
        now = self._clock.now()
        for _ in range(3):
            current = self._store.get(session_id, now)
            if current.state != SessionState.GENERATING.value:
                return False
            validate_transition(SessionState.GENERATING, SessionState.READY)
            updated = current.model_copy(
                update={
                    "state": SessionState.READY.value,
                    "lesson": lesson,
                    "stage_events": events,
                    "updated_at": now,
                }
            )
            try:
                self._store.put_if_version(updated, current.version)
            except VersionConflict:
                continue
            return True
        return False
