"""Learning-loop service: baseline, answers, hints, advance, end check and summary.

Covers R-05.2 to R-05.8, R-07.1, R-07.2, R-07.6, R-08.3, R-10.9; NFR-02, NFR-05.

* Baseline is shown first. Until it is answered or skipped (READY -> BASELINE -> ACTIVE), no
  Activity can be answered (R-07.1, R-07.6). A skipped question is stored as ``SKIPPED``.
* Answers are validated (empty, over 2,000 characters, wrong format) before any write, so a
  rejected answer leaves progress unchanged (R-05.4). Grading is deterministic first through the
  :class:`AssessmentService`; deterministic verdicts make no model call (R-05.2, R-06.5). The
  mutation and its idempotency record commit in one conditional write (R-05.3).
* Hints never contain the expected answer and never change the Activity status (R-05.5).
* ``advance`` persists completed/skipped then moves on. If persisting fails, the Session is
  untouched, so the Learner stays on the same Activity and can retry (R-05.6, R-05.7, R-10.9).
* The End_Question has the same topic and answer scale as the Baseline_Question with different
  wording (R-07.2). An observed difference exists only when both were answered (R-07.3 to R-07.5).
* Every write is rejected once the Session is stopped (R-08.3).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.session_store import Clock, SessionStore, SystemClock, VersionConflict
from app.agents.budget import RequestBudget
from app.agents.orchestrator import AssessRequest, Orchestrator
from app.agents.stage_events import StageEventLog
from app.config import Settings
from app.domain.models import (
    Activity,
    ActivityStatus,
    AnswerEntry,
    Assessment,
    AssessmentStatus,
    Lesson,
    ObjectInventory,
    Question,
    SessionRecord,
    SessionSummary,
)
from app.domain.state_machine import (
    SessionState,
    WriteOperation,
    check_write_allowed,
    validate_transition,
)
from app.services import gates, grading, idempotency
from app.services.assessment_service import (
    AssessmentResult,
    AssessmentService,
    Assessor,
    MasteryObservation,
    provisional_mastery_estimate,
)
from app.services.learner_view import LearnerView, project_learner_view
from app.services.lesson_service import LessonError

ANSWERS_ROUTE = "POST /sessions/{id}/answers"
SKIPPED = -1  # stored marker for a skipped Baseline_Question / End_Question
MAX_COMMIT_ATTEMPTS = 3
MAX_ANSWER_CHARS = 2000
NOT_VALIDATED_WARNING = (
    "This is an observed difference only. It is not a validated educational assessment."
)
GENERIC_SCAFFOLD = "Look at your objects again and try it one small step at a time."

T = TypeVar("T")


class LearningLoopError(LessonError):
    """Request-level learning-loop error with an API ``code`` and HTTP status."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PersistFailed(LearningLoopError):  # noqa: N818
    """Progress could not be saved; state is unchanged and the action can be retried (R-05.7)."""

    def __init__(self) -> None:
        super().__init__(
            "persist_failed",
            "progress could not be saved; you stay on this step, please try again",
            503,
        )


# --- request / response models ---------------------------------------------------------------


class QuestionAnswer(BaseModel):
    """Answer or skip for the Baseline_Question and End_Question (R-07.1, R-07.2)."""

    model_config = ConfigDict(extra="forbid")

    answer: int | None = Field(default=None, ge=0, le=10)
    skipped: bool = False


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1)
    outcome: Literal["completed", "skipped"]


class QuestionView(BaseModel):
    question_id: str
    topic: str
    prompt: str
    scale_max: int
    can_skip: bool = True


class AnswerResult(BaseModel):
    activity_id: str
    status: AssessmentStatus
    explanation: str
    clarification_requested: bool = False
    clarification_prompt: str | None = None
    offer_skip_or_hint: bool = False
    excluded_from_mastery: bool = False
    adjustment_note: str | None = None
    replayed: bool = False
    view: LearnerView


class HintResult(BaseModel):
    activity_id: str
    hint: str
    hints_used: int
    activity_status: Literal["pending", "completed", "skipped"]


class AdvanceResult(BaseModel):
    state: str
    finished: bool
    view: LearnerView


class QuestionResult(BaseModel):
    state: str
    view: LearnerView | None = None
    summary: SessionSummary | None = None


# --- helpers ---------------------------------------------------------------------------------


def orchestrator_assessor(orchestrator: Orchestrator, settings: Settings) -> Assessor:
    """Adapt the Orchestrator's assessment stage to the AssessmentService assessor shape."""

    async def assess(activity: Activity, answer: str) -> Assessment:
        budget = RequestBudget.for_assessment(settings)
        return await asyncio.wait_for(
            orchestrator.assess(
                AssessRequest(activity=activity, answer=answer), budget, StageEventLog()
            ),
            timeout=settings.assessment_deadline_seconds,
        )

    return assess


def end_question_for(lesson: Lesson) -> Question:
    """End_Question: same topic and scale as the baseline, different wording (R-07.2)."""
    base, end = lesson.baseline_question, lesson.end_question
    prompt = end.prompt
    if " ".join(prompt.split()).casefold() == " ".join(base.prompt.split()).casefold():
        prompt = f"Now, {base.prompt[:1].lower()}{base.prompt[1:]}"[:300]
    return end.model_copy(
        update={"topic": base.topic, "scale_max": base.scale_max, "prompt": prompt}
    )


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def leaks_answer(hint: str, expected: str) -> bool:
    """Whether a hint contains the expected answer text (R-05.5)."""
    norm_hint = " ".join(hint.casefold().split())
    norm_expected = " ".join(expected.casefold().split())
    if norm_expected and re.search(rf"(?<!\w){re.escape(norm_expected)}(?!\w)", norm_hint):
        return True
    try:
        target = Decimal(norm_expected.replace(",", ""))
    except InvalidOperation:
        return False
    for token in _NUMBER.findall(norm_hint.replace(",", "")):
        if Decimal(token) == target:
            return True
    return False


def _status_of(record: SessionRecord, activity_id: str) -> ActivityStatus:
    for status in record.activity_status:
        if status.activity_id == activity_id:
            return status
    return ActivityStatus(activity_id=activity_id)


def _with_status(record: SessionRecord, new: ActivityStatus) -> list[ActivityStatus]:
    existing = {s.activity_id: s for s in record.activity_status}
    existing[new.activity_id] = new
    activities = record.lesson.activities if record.lesson else []
    return [existing.get(a.id, ActivityStatus(activity_id=a.id)) for a in activities]


class LearningLoopService:
    def __init__(
        self,
        store: SessionStore,
        assessment: AssessmentService,
        settings: Settings,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._assessment = assessment
        self._settings = settings
        self._clock: Clock = clock or SystemClock()

    # -- persistence helper -------------------------------------------------------------------

    def _commit(
        self,
        session_id: str,
        build: Callable[[SessionRecord], tuple[SessionRecord | None, T]],
    ) -> T:
        """Read, build and conditionally write; retry version conflicts, wrap other failures."""
        for _ in range(MAX_COMMIT_ATTEMPTS):
            record = self._store.get(session_id, self._clock.now())
            updated, result = build(record)
            if updated is None:
                return result
            try:
                self._store.put_if_version(updated, record.version)
            except VersionConflict:
                continue
            except Exception as exc:
                raise PersistFailed() from exc
            return result
        raise PersistFailed()

    @staticmethod
    def _guard_write(record: SessionRecord) -> SessionState:
        state = SessionState(record.state)
        check_write_allowed(state, WriteOperation.ANSWER)  # R-08.3
        return state

    @staticmethod
    def _lesson(record: SessionRecord) -> Lesson:
        if record.lesson is None:
            raise LearningLoopError("no_lesson", "this session has no lesson yet")
        return record.lesson

    def _touch(self, record: SessionRecord, **update: object) -> SessionRecord:
        return record.model_copy(update={**update, "updated_at": self._clock.now()})

    # -- reads --------------------------------------------------------------------------------

    def learner_view(self, record: SessionRecord) -> LearnerView:
        self._lesson(record)
        return project_learner_view(record)

    def baseline_question(self, record: SessionRecord) -> QuestionView:
        lesson = self._lesson(record)
        if record.state not in (SessionState.READY.value, SessionState.BASELINE.value):
            raise LearningLoopError("invalid_state", "the baseline question is no longer open")
        q = lesson.baseline_question
        return QuestionView(question_id=q.id, topic=q.topic, prompt=q.prompt, scale_max=q.scale_max)

    def end_question(self, record: SessionRecord) -> QuestionView:
        lesson = self._lesson(record)
        if record.state != SessionState.END_CHECK.value:
            raise LearningLoopError("invalid_state", "the end question is not open yet")
        q = end_question_for(lesson)
        return QuestionView(question_id=q.id, topic=q.topic, prompt=q.prompt, scale_max=q.scale_max)

    # -- baseline and end check ---------------------------------------------------------------

    def submit_baseline(self, session_id: str, body: QuestionAnswer) -> QuestionResult:
        """Answer or skip the Baseline_Question; READY -> BASELINE -> ACTIVE (R-07.1, R-07.6)."""
        value = self._question_value(body)

        def build(record: SessionRecord) -> tuple[SessionRecord | None, QuestionResult]:
            state = self._guard_write(record)
            lesson = self._lesson(record)
            if state is not SessionState.READY:
                if record.baseline == value and record.baseline is not None:
                    return None, QuestionResult(
                        state=record.state, view=project_learner_view(record)
                    )
                raise LearningLoopError("invalid_state", "the baseline question is no longer open")
            self._check_scale(body, lesson.baseline_question)
            validate_transition(SessionState.READY, SessionState.BASELINE)
            validate_transition(SessionState.BASELINE, SessionState.ACTIVE)
            updated = self._touch(
                record,
                state=SessionState.ACTIVE.value,
                baseline=value,
                activity_status=[ActivityStatus(activity_id=a.id) for a in lesson.activities],
            )
            return updated, QuestionResult(state=updated.state, view=project_learner_view(updated))

        return self._commit(session_id, build)

    def submit_end_check(self, session_id: str, body: QuestionAnswer) -> QuestionResult:
        """Answer or skip the End_Question; END_CHECK -> COMPLETED (R-07.2)."""
        value = self._question_value(body)

        def build(record: SessionRecord) -> tuple[SessionRecord | None, QuestionResult]:
            state = self._guard_write(record)
            lesson = self._lesson(record)
            if state is not SessionState.END_CHECK:
                if state is SessionState.COMPLETED and record.end_answer == value:
                    return None, QuestionResult(state=record.state, summary=self.summary(record))
                raise LearningLoopError("invalid_state", "the end question is not open")
            self._check_scale(body, end_question_for(lesson))
            validate_transition(SessionState.END_CHECK, SessionState.COMPLETED)
            updated = self._touch(record, state=SessionState.COMPLETED.value, end_answer=value)
            return updated, QuestionResult(state=updated.state, summary=self.summary(updated))

        return self._commit(session_id, build)

    @staticmethod
    def _question_value(body: QuestionAnswer) -> int:
        if body.skipped == (body.answer is not None):
            raise LearningLoopError(
                "invalid_answer", "send either an answer or skipped=true, not both or neither", 422
            )
        return SKIPPED if body.skipped else int(body.answer or 0)

    @staticmethod
    def _check_scale(body: QuestionAnswer, question: Question) -> None:
        if body.answer is not None and body.answer > question.scale_max:
            raise LearningLoopError(
                "invalid_answer", f"the answer must be between 0 and {question.scale_max}", 422
            )

    # -- answers ------------------------------------------------------------------------------

    async def submit_answer(self, session_id: str, key: str, answer: str) -> AnswerResult:
        """Validate, grade, adapt and persist one answer exactly once per key (R-05.2 to R-05.4)."""
        payload_hash = idempotency.compute_payload_hash({"route": ANSWERS_ROUTE, "answer": answer})
        record = self._store.get(session_id, self._clock.now())
        prep = self._prepare_answer(record, key, payload_hash, answer)
        if isinstance(prep, AnswerResult):
            return prep
        activity, index = prep
        status = _status_of(record, activity.id)
        objective = self._lesson(record).objective
        try:
            result = await self._assessment.assess(
                activity,
                answer.strip(),
                record.age_band,
                prior_clarifications=status.clarifications,
                objective=objective,
                inventory=ObjectInventory(items=record.objects),
            )
        except Exception as exc:  # model failure or timeout: nothing was written
            raise LearningLoopError(
                "assessment_unavailable", "the answer could not be checked; please try again", 503
            ) from exc

        def build(rec: SessionRecord) -> tuple[SessionRecord | None, AnswerResult]:
            again = self._prepare_answer(rec, key, payload_hash, answer)
            if isinstance(again, AnswerResult):
                return None, again
            if again[0].id != activity.id:
                raise LearningLoopError("activity_not_current", "the current activity changed")
            updated, note = self._apply_answer(rec, activity, index, answer, result)
            view = project_learner_view(updated)
            reply = AnswerResult(
                activity_id=activity.id,
                status=result.assessment.status,
                explanation=result.assessment.explanation,
                clarification_requested=result.clarification_requested,
                clarification_prompt=result.clarification_prompt,
                offer_skip_or_hint=result.offer_skip_or_hint,
                excluded_from_mastery=result.excluded_from_mastery,
                adjustment_note=note,
                view=view,
            )
            now = self._clock.now()
            records = idempotency.append_record(
                rec.idempotency,
                key,
                ANSWERS_ROUTE,
                payload_hash,
                now,
                result_ref=reply.model_dump_json(),
                window=_window(self._settings),
            )
            return updated.model_copy(update={"idempotency": records}), reply

        return self._commit(session_id, build)

    def _prepare_answer(
        self, record: SessionRecord, key: str, payload_hash: str, answer: str
    ) -> AnswerResult | tuple[Activity, int]:
        state = self._guard_write(record)
        now = self._clock.now()
        existing = idempotency.lookup(
            record.idempotency, key, payload_hash, now, window=_window(self._settings)
        )
        if existing is not None and existing.result_ref:
            return AnswerResult.model_validate_json(existing.result_ref).model_copy(
                update={"replayed": True}
            )
        if state is not SessionState.ACTIVE:
            raise LearningLoopError("invalid_state", "answers are accepted only during the lesson")
        activity, index = self._current(record)
        if not answer.strip():
            raise LearningLoopError("invalid_answer", "the answer is empty", 422)
        if len(answer) > MAX_ANSWER_CHARS:
            raise LearningLoopError(
                "invalid_answer", f"the answer is longer than {MAX_ANSWER_CHARS} characters", 422
            )
        if not grading.matches_format(activity, answer):
            raise LearningLoopError(
                "invalid_answer",
                f"the answer does not match the expected format ({activity.answer_kind})",
                422,
            )
        if any(a.activity_id == activity.id for a in record.answers):
            raise LearningLoopError(
                "activity_already_answered", "this activity was already answered; move on"
            )
        return activity, index

    def _apply_answer(
        self,
        record: SessionRecord,
        activity: Activity,
        index: int,
        answer: str,
        result: AssessmentResult,
    ) -> tuple[SessionRecord, str | None]:
        assessment = result.assessment
        status = _status_of(record, activity.id)
        unclear = assessment.status is AssessmentStatus.UNASSESSABLE
        new_status = status.model_copy(
            update={
                "attempts": status.attempts + 1,
                "clarifications": result.clarifications_used,
                "assessment": assessment.status,
                "excluded": result.excluded_from_mastery,
            }
        )
        answers = record.answers
        lesson = self._lesson(record)
        note: str | None = None
        if not unclear:  # unclear answers are not stored as marked answers (R-06.3)
            answers = [*answers, AnswerEntry(activity_id=activity.id, answer=answer.strip())]
            lesson, applied = self._adapt_next(record, lesson, index, activity, result)
            note = assessment.adjustment_note if applied else None
        updated = self._touch(
            record,
            answers=answers,
            lesson=lesson,
            activity_status=_with_status(record, new_status),
        )
        return updated, note

    def _adapt_next(
        self,
        record: SessionRecord,
        lesson: Lesson,
        index: int,
        current: Activity,
        result: AssessmentResult,
    ) -> tuple[Lesson, bool]:
        """Apply the adaptation to the next Activity, only if it passes every gate (R-06.2)."""
        adapted = result.adapted_activity
        if adapted is None or index + 1 >= len(lesson.activities):
            return lesson, False
        nxt = lesson.activities[index + 1]
        if adapted.difficulty < current.difficulty:
            update: dict[str, object] = {"difficulty": max(1, nxt.difficulty - 1)}
        else:
            update = {"hints": [adapted.hints[0], *nxt.hints][:3]}
        candidate = nxt.model_copy(update=update)
        if not gates.check_activity(candidate, ObjectInventory(items=record.objects)).passed:
            return lesson, False
        activities = list(lesson.activities)
        activities[index + 1] = candidate
        return lesson.model_copy(update={"activities": activities}), True

    def _current(self, record: SessionRecord) -> tuple[Activity, int]:
        lesson = self._lesson(record)
        index = record.current_index
        if index >= len(lesson.activities):
            raise LearningLoopError("no_active_activity", "there is no activity left")
        return lesson.activities[index], index

    # -- hint ---------------------------------------------------------------------------------

    def hint(self, session_id: str) -> HintResult:
        """Return a scaffold without the expected answer; the Activity status is unchanged."""

        def build(record: SessionRecord) -> tuple[SessionRecord | None, HintResult]:
            state = self._guard_write(record)
            if state is not SessionState.ACTIVE:
                raise LearningLoopError("invalid_state", "hints are available during the lesson")
            activity, _ = self._current(record)
            status = _status_of(record, activity.id)
            safe = [h for h in activity.hints if not leaks_answer(h, activity.expected_answer)]
            text = safe[min(status.hints_used, len(safe) - 1)] if safe else GENERIC_SCAFFOLD
            result = HintResult(
                activity_id=activity.id,
                hint=text,
                hints_used=status.hints_used + 1,
                activity_status=status.status,
            )
            updated = self._touch(
                record,
                activity_status=_with_status(
                    record, status.model_copy(update={"hints_used": status.hints_used + 1})
                ),
            )
            return updated, result

        return self._commit(session_id, build)

    # -- advance ------------------------------------------------------------------------------

    def advance(self, session_id: str, body: AdvanceRequest) -> AdvanceResult:
        """Persist completed/skipped and advance; on persist failure nothing changes (R-05.6/7)."""

        def build(record: SessionRecord) -> tuple[SessionRecord | None, AdvanceResult]:
            state = self._guard_write(record)
            lesson = self._lesson(record)
            prior = _status_of(record, body.activity_id)
            if prior.status == body.outcome:  # retry after a lost response: replay
                return None, self._advance_result(record)
            if state is not SessionState.ACTIVE:
                raise LearningLoopError("invalid_state", "the lesson is not active")
            activity, index = self._current(record)
            if activity.id != body.activity_id:
                raise LearningLoopError("activity_not_current", "that is not the current activity")
            if body.outcome == "completed" and not any(
                a.activity_id == activity.id for a in record.answers
            ):
                raise LearningLoopError(
                    "activity_not_answered", "answer the activity first, or skip it"
                )
            next_index = index + 1
            finished = next_index >= len(lesson.activities)
            target = SessionState.END_CHECK if finished else SessionState.ACTIVE
            validate_transition(SessionState.ACTIVE, target)
            updated = self._touch(
                record,
                state=target.value,
                current_index=next_index,
                activity_status=_with_status(
                    record, prior.model_copy(update={"status": body.outcome})
                ),
            )
            return updated, self._advance_result(updated)

        return self._commit(session_id, build)

    @staticmethod
    def _advance_result(record: SessionRecord) -> AdvanceResult:
        return AdvanceResult(
            state=record.state,
            finished=record.state != SessionState.ACTIVE.value,
            view=project_learner_view(record),
        )

    # -- summary ------------------------------------------------------------------------------

    def summary(self, record: SessionRecord) -> SessionSummary:
        """Concepts practiced, next steps and a provisional estimate (R-05.8, R-06.6, R-07.3+)."""
        lesson = self._lesson(record)
        statuses = [_status_of(record, a.id) for a in lesson.activities]
        practiced = [s for s in statuses if s.status != "pending" or s.assessment is not None]
        concepts = [lesson.objective] if practiced else []
        skipped = any(s.status == "skipped" for s in statuses)
        needs_support = any(s.assessment is AssessmentStatus.SUPPORT for s in statuses)
        steps = []
        if skipped or needs_support:
            steps.append(
                "Revisit the steps that were skipped or felt tricky, using the same objects."
            )
        steps.append(
            "Try the same idea again with different objects or bigger numbers, "
            "with an adult nearby."
        )
        estimate = provisional_mastery_estimate(
            [
                MasteryObservation(status=s.assessment, excluded=s.excluded)
                for s in statuses
                if s.assessment is not None
            ]
        )
        base_skipped = record.baseline == SKIPPED
        end_skipped = record.end_answer == SKIPPED
        baseline = record.baseline if record.baseline not in (None, SKIPPED) else None
        end = record.end_answer if record.end_answer not in (None, SKIPPED) else None
        both = baseline is not None and end is not None
        return SessionSummary(
            concepts_practiced=concepts,
            next_steps=steps,
            baseline=baseline,
            end_answer=end,
            difference=(end - baseline)
            if both and end is not None and baseline is not None
            else None,
            baseline_skipped=base_skipped,
            end_skipped=end_skipped,
            provisional_estimate=estimate,
            warning=NOT_VALIDATED_WARNING if both else None,
        )


def _window(settings: Settings) -> timedelta:
    return timedelta(hours=settings.idempotency_window_hours)
