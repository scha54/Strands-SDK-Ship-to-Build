"""Orchestrator: runs the specialists in order (R-04.1, R-04.2, R-04.3, R-04.5-R-04.7).

``generate_lesson`` calls Environment, Curriculum and Storytelling in that order and
``assess`` calls the Assessment_Specialist. Each output is re-validated against its
versioned Specialist_Contract and the contract version is recorded in the Stage_Event.
A failing specialist is retried up to the configured retry limit; after that an error
naming the specialist is raised. The orchestrator never touches the Session_Store, so
a failed run persists nothing. ``LimitReached`` stops the run with a failed
Stage_Event and an error naming the limit. A :class:`CancelToken` (set on Stop)
cancels the pending model call (R-08.3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.adapters.bedrock import CircuitOpen, ModelError
from app.agents.budget import LimitName, LimitReached, RequestBudget
from app.agents.stage_events import StageEmitter
from app.config import Settings
from app.domain.models import (
    CONTRACT_VERSION,
    Activity,
    AgeBand,
    Assessment,
    AssessmentOutput,
    CurriculumPlan,
    EnvironmentOutput,
    Lesson,
    ObjectInventory,
    Question,
    StoryDraft,
    Subject,
)

T = TypeVar("T", bound=BaseModel)

# Stage names for the five-stage timeline (R-12.2) and the specialist identifiers.
STAGE_ENVIRONMENT = "understand_objects"
STAGE_CURRICULUM = "choose_objective"
STAGE_STORY = "create_story"
STAGE_ASSESS = "assess_answer"


class OrchestrationError(Exception):
    """Base class; ``code`` is a stable machine-readable error code."""

    code: str = "orchestration_error"


class SpecialistFailed(OrchestrationError):  # noqa: N818
    """A specialist failed after all retries (R-04.3, R-04.6)."""

    code = "specialist_failed"

    def __init__(self, specialist: str, attempts: int) -> None:
        super().__init__(f"specialist '{specialist}' failed after {attempts} attempts")
        self.specialist = specialist
        self.attempts = attempts


class LimitExceeded(OrchestrationError):  # noqa: N818
    """A request limit was reached; names the limit (R-04.7)."""

    code = "limit_reached"

    def __init__(self, limit_name: LimitName) -> None:
        super().__init__(f"request limit reached: {limit_name}")
        self.limit_name: LimitName = limit_name


class Cancelled(OrchestrationError):  # noqa: N818
    """The request was cancelled because the session was stopped (R-08.3)."""

    code = "stopped"

    def __init__(self) -> None:
        super().__init__("request cancelled: session stopped")


class CancelToken:
    """Set when the Facilitator presses Stop; pending model calls are cancelled."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class LessonRequest(BaseModel):
    age_band: AgeBand
    subject: Subject
    objects: list[str]


class AssessRequest(BaseModel):
    activity: Activity
    answer: str


class _EnvironmentLike(Protocol):
    async def run(self, objects: list[str], budget: RequestBudget) -> EnvironmentOutput: ...


class _CurriculumLike(Protocol):
    async def run(
        self,
        inventory: ObjectInventory,
        age_band: AgeBand,
        subject: Subject,
        budget: RequestBudget,
    ) -> CurriculumPlan: ...


class _StorytellingLike(Protocol):
    async def run(
        self, inventory: ObjectInventory, plan: CurriculumPlan, budget: RequestBudget
    ) -> StoryDraft: ...


class _AssessmentLike(Protocol):
    async def run(
        self, activity: Activity, answer: str, budget: RequestBudget
    ) -> AssessmentOutput: ...


class _InvalidOutput(Exception):
    """Output failed contract re-validation (internal)."""


def _validated(output: T, expected: type[T]) -> T:
    """Re-validate against the contract and check the contract version (R-04.3)."""
    try:
        checked = expected.model_validate(output.model_dump())
    except ValidationError as exc:
        raise _InvalidOutput(expected.__name__) from exc
    if getattr(checked, "contract_version", None) != CONTRACT_VERSION:
        raise _InvalidOutput(expected.__name__)
    return checked


class Orchestrator:
    def __init__(
        self,
        *,
        environment: _EnvironmentLike,
        curriculum: _CurriculumLike,
        storytelling: _StorytellingLike,
        assessment: _AssessmentLike,
        settings: Settings,
    ) -> None:
        self._environment = environment
        self._curriculum = curriculum
        self._storytelling = storytelling
        self._assessment = assessment
        self._retries = settings.specialist_retries

    async def generate_lesson(
        self,
        req: LessonRequest,
        budget: RequestBudget,
        emit: StageEmitter,
        cancel: CancelToken | None = None,
    ) -> Lesson:
        env = await self._stage(
            STAGE_ENVIRONMENT,
            "environment",
            EnvironmentOutput,
            lambda: self._environment.run(req.objects, budget),
            emit,
            cancel,
        )
        plan = await self._stage(
            STAGE_CURRICULUM,
            "curriculum",
            CurriculumPlan,
            lambda: self._curriculum.run(env.inventory, req.age_band, req.subject, budget),
            emit,
            cancel,
        )
        story = await self._stage(
            STAGE_STORY,
            "storytelling",
            StoryDraft,
            lambda: self._storytelling.run(env.inventory, plan, budget),
            emit,
            cancel,
        )
        return _assemble_lesson(env.inventory, plan, story)

    async def assess(
        self,
        req: AssessRequest,
        budget: RequestBudget,
        emit: StageEmitter,
        cancel: CancelToken | None = None,
    ) -> Assessment:
        out = await self._stage(
            STAGE_ASSESS,
            "assessment",
            AssessmentOutput,
            lambda: self._assessment.run(req.activity, req.answer, budget),
            emit,
            cancel,
        )
        return out.assessment

    async def _stage(
        self,
        stage: str,
        specialist: str,
        contract: type[T],
        call: Callable[[], Awaitable[T]],
        emit: StageEmitter,
        cancel: CancelToken | None,
    ) -> T:
        """One started event, then exactly one completed or failed event (R-04.5)."""
        emit(stage, specialist, "started")
        attempts = self._retries + 1
        try:
            for _ in range(attempts):
                try:
                    output = await _run_cancellable(call(), cancel)
                    checked = _validated(output, contract)
                except (ModelError, _InvalidOutput) as exc:
                    if isinstance(exc, CircuitOpen):
                        raise SpecialistFailed(specialist, 1) from exc
                    continue
                emit(stage, specialist, "completed", checked.contract_version)  # type: ignore[attr-defined]
                return checked
            raise SpecialistFailed(specialist, attempts)
        except LimitReached as exc:
            _emit_failed(emit, stage, specialist)
            raise LimitExceeded(exc.limit_name) from exc
        except OrchestrationError:
            _emit_failed(emit, stage, specialist)
            raise


def _emit_failed(emit: StageEmitter, stage: str, specialist: str) -> None:
    emit(stage, specialist, "failed")


async def _run_cancellable(coro: Awaitable[T], cancel: CancelToken | None) -> T:
    """Await ``coro``; if ``cancel`` is set first, cancel the pending call (R-08.3)."""
    if cancel is None:
        return await coro
    if cancel.is_set:
        if asyncio.iscoroutine(coro):
            coro.close()
        raise Cancelled
    task = asyncio.ensure_future(coro)
    waiter = asyncio.ensure_future(cancel.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            return task.result()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        raise Cancelled
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()


def _assemble_lesson(inventory: ObjectInventory, plan: CurriculumPlan, story: StoryDraft) -> Lesson:
    """Combine validated specialist outputs into a Lesson (not yet gated or stored)."""
    usable = [i for i in inventory.items if not i.excluded_reason]
    required = {
        " ".join(o.split()).casefold() for a in story.activities for o in a.required_objects
    }
    ordered = [i.original for i in usable if i.normalized in required] + [
        i.original for i in usable if i.normalized not in required
    ]
    topic = plan.objective[:100]
    try:
        return Lesson(
            source="generated",
            title=story.title,
            objective=plan.objective,
            objects=ordered[:10],
            setup=story.setup,
            activities=story.activities,
            baseline_question=Question(
                id="baseline",
                topic=topic,
                prompt=f"How confident are you about: {topic}?"[:300],
                scale_max=5,
            ),
            end_question=Question(
                id="end",
                topic=topic,
                prompt=f"Now, how confident are you about: {topic}?"[:300],
                scale_max=5,
            ),
            estimated_minutes=10,
        )
    except ValidationError as exc:
        raise SpecialistFailed("storytelling", 1) from exc


__all__ = [
    "AssessRequest",
    "CancelToken",
    "Cancelled",
    "LessonRequest",
    "LimitExceeded",
    "OrchestrationError",
    "Orchestrator",
    "SpecialistFailed",
]
