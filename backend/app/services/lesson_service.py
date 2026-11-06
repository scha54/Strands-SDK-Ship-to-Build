"""Lesson service: gated generation, Safe_Template fallback and persistence.

Covers R-03.1, R-03.4, R-03.5, R-04.5, R-11.1, R-11.2; NFR-05, NFR-10.

* :meth:`LessonService.start` validates the request, applies idempotency (a repeated key and
  payload never regenerates, R-11.2), enforces the per-session generation cap, redacts PII
  before any model call (R-08.6, R-08.7) and reserves the Session by moving it to
  ``GENERATING`` in one conditional write together with the idempotency record (R-11.1).
* :meth:`LessonService.run` performs the work: up to 1 initial attempt plus
  ``lesson_generation_retries`` retries when the Validation_Gates reject a Lesson (R-03.4).
  On exhaustion it returns the labeled Safe_Template for the Age_Band and Subject, or a failure
  with no Lesson persisted when none exists (R-03.5). A model error or timeout cancels the call
  and returns an error offering retry and Safe_Template while the inputs stay in the Session.
* The Lesson is persisted with a conditional write (``GENERATING`` -> ``READY``, or ``FAILED``).
  A Session stopped meanwhile is never overwritten.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.adapters.session_store import Clock, SessionStore, SystemClock, VersionConflict
from app.agents.budget import RequestBudget
from app.agents.orchestrator import (
    Cancelled,
    CancelToken,
    LessonRequest,
    OrchestrationError,
    Orchestrator,
)
from app.config import Settings
from app.domain.models import (
    AgeBand,
    AgentStageEvent,
    GateResult,
    Lesson,
    ObjectInventory,
    ObjectItem,
    SessionRecord,
    Subject,
    _norm,
)
from app.domain.state_machine import (
    SESSION_STOPPED_CODE,
    SessionState,
    StateMachineError,
    validate_transition,
)
from app.services import idempotency
from app.services.gates import check_lesson
from app.services.grounding import handle_hazards, label_ambiguous
from app.services.pii import PiiNotRedactableError, redact_pii
from app.services.safe_templates import SAFE_TEMPLATE_LABEL, build_safe_template

LESSONS_ROUTE = "POST /sessions/{id}/lessons"

Mode = Literal["generate", "safe_template"]
TemplateBuilder = Callable[[AgeBand, Subject, str], Lesson | None]
OPTION_RETRY = "retry"
OPTION_SAFE_TEMPLATE = "safe_template"


class LessonError(Exception):
    """Request-level lesson error with an API ``code`` and HTTP ``status_code``."""

    status_code = 409
    code = "lesson_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GenerationCapReached(LessonError):  # noqa: N818
    """The per-session generation cap was reached (R-11.1)."""

    status_code = 429
    code = "generation_cap_reached"

    def __init__(self, cap: int) -> None:
        super().__init__(f"this session already used its {cap} lesson generations")
        self.cap = cap


class PiiRemovalRequired(LessonError):  # noqa: N818
    """PII could not be redacted; no model call was made and session data is unchanged."""

    status_code = 422
    code = "pii_not_redactable"


class NoUsableObjects(LessonError):  # noqa: N818
    """Every Object was excluded as hazardous, so no Lesson can be built."""

    status_code = 422
    code = "no_usable_objects"

    def __init__(self) -> None:
        super().__init__("no usable objects remain after safety exclusions")


@dataclass(frozen=True)
class StartResult:
    """Outcome of :meth:`LessonService.start`."""

    state: str
    replayed: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LessonOutcome:
    """Result of :meth:`LessonService.run`.

    ``status`` is ``ready`` (Lesson persisted, possibly a labeled Safe_Template), ``failed``
    (nothing persisted; ``options`` lists what the Facilitator can do next) or ``stopped``.
    """

    status: Literal["ready", "failed", "stopped"]
    lesson: Lesson | None = None
    source: str | None = None
    label: str | None = None
    error_code: str | None = None
    options: tuple[str, ...] = ()
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    gate_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Prepared:
    inventory: ObjectInventory
    usable: list[str]
    warnings: list[str]
    notices: list[str]


class LessonService:
    def __init__(
        self,
        store: SessionStore,
        orchestrator: Orchestrator,
        settings: Settings,
        *,
        clock: Clock | None = None,
        template_builder: TemplateBuilder = build_safe_template,
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._settings = settings
        self._clock: Clock = clock or SystemClock()
        self._cancels: dict[str, CancelToken] = {}
        self._failures: dict[str, tuple[str, tuple[str, ...]]] = {}
        # Injectable so tests can show the "no template exists" branch.
        self._build_template = template_builder

    # -- public API ---------------------------------------------------------------------------

    def start(self, session_id: str, key: str, mode: Mode = "generate") -> StartResult:
        """Validate and reserve a generation; idempotent per key and payload (R-11.1, R-11.2)."""
        now = self._clock.now()
        record = self._store.get(session_id, now)
        payload_hash = idempotency.compute_payload_hash({"route": LESSONS_ROUTE, "mode": mode})
        window = _window(self._settings)
        existing = idempotency.lookup(record.idempotency, key, payload_hash, now, window=window)
        if existing is not None:
            return StartResult(state=record.state, replayed=True)

        current = SessionState(record.state)
        if current is SessionState.STOPPED:
            raise StateMachineError(
                "session is stopped; generation is not allowed", SESSION_STOPPED_CODE
            )
        cap = self._settings.max_generations_per_session
        if mode == "generate" and record.generation_count >= cap:
            raise GenerationCapReached(cap)
        validate_transition(current, SessionState.GENERATING)
        prepared = self._prepare(record)  # raises before any write

        updated = record.model_copy(
            update={
                "state": SessionState.GENERATING.value,
                "updated_at": now,
                "generation_count": record.generation_count + (1 if mode == "generate" else 0),
                "idempotency": idempotency.append_record(
                    record.idempotency, key, LESSONS_ROUTE, payload_hash, now, window=window
                ),
            }
        )
        self._store.put_if_version(updated, record.version)
        return StartResult(
            state=SessionState.GENERATING.value, replayed=False, warnings=prepared.warnings
        )

    def last_failure(self, session_id: str) -> tuple[str, tuple[str, ...]] | None:
        """Error code and options of the latest failed generation (diagnostic, not persisted)."""
        return self._failures.get(session_id) or (
            "generation_failed",
            (OPTION_RETRY, OPTION_SAFE_TEMPLATE),
        )

    def cancel(self, session_id: str) -> None:
        """Cancel a pending generation (called on Stop, R-08.3)."""
        token = self._cancels.get(session_id)
        if token is not None:
            token.set()

    async def run(self, session_id: str, mode: Mode = "generate") -> LessonOutcome:
        """Generate (or template) the Lesson for a reserved Session and persist the result."""
        record = self._store.get(session_id, self._clock.now())
        if record.state != SessionState.GENERATING.value:
            return LessonOutcome(status="stopped")
        prepared = self._prepare(record)
        cancel = CancelToken()
        self._cancels[session_id] = cancel
        try:
            outcome = await self._produce(record, prepared, mode, cancel)
        except Exception:  # unexpected fault: fail the generation, keep inputs
            outcome = self._model_failure("internal_error", 0, prepared.warnings)
        finally:
            self._cancels.pop(session_id, None)
        if outcome.status == "failed" and outcome.error_code:
            self._failures[session_id] = (outcome.error_code, outcome.options)
        else:
            self._failures.pop(session_id, None)
        return self._persist(session_id, outcome)

    # -- generation ---------------------------------------------------------------------------

    async def _produce(
        self, record: SessionRecord, prepared: _Prepared, mode: Mode, cancel: CancelToken
    ) -> LessonOutcome:
        warnings = prepared.warnings
        if mode == "safe_template":
            return self._template_outcome(record, prepared, attempts=0) or self._failure(
                "no_safe_template", attempts=0, warnings=warnings, options=(OPTION_RETRY,)
            )

        request = LessonRequest(
            age_band=record.age_band, subject=record.subject, objects=prepared.usable
        )
        attempts = 1 + self._settings.lesson_generation_retries
        reasons: list[str] = []
        used = 0
        for _ in range(attempts):
            used += 1
            emit = _PersistingEmitter(self._store, record.session_id, self._clock)
            budget = RequestBudget.for_generation(self._settings)
            try:
                lesson = await asyncio.wait_for(
                    self._orchestrator.generate_lesson(request, budget, emit, cancel),
                    timeout=self._settings.generation_deadline_seconds,
                )
            except Cancelled:
                return LessonOutcome(status="stopped", attempts=used, warnings=warnings)
            except TimeoutError:
                return self._model_failure("model_timeout", used, warnings)
            except OrchestrationError as exc:
                return self._model_failure(exc.code, used, warnings)

            gate = _gate(lesson, prepared, record)
            if gate.passed:
                return LessonOutcome(
                    status="ready",
                    lesson=lesson,
                    source="generated",
                    attempts=used,
                    warnings=warnings,
                )
            reasons = gate.reasons

        fallback = self._template_outcome(record, prepared, attempts=used)
        if fallback is not None:
            return LessonOutcome(
                status="ready",
                lesson=fallback.lesson,
                source=fallback.source,
                label=fallback.label,
                attempts=used,
                warnings=warnings,
                gate_reasons=reasons,
            )
        return self._failure(
            "gates_failed",
            attempts=used,
            warnings=warnings,
            options=(OPTION_RETRY,),
            reasons=reasons,
        )

    def _template_outcome(
        self, record: SessionRecord, prepared: _Prepared, attempts: int
    ) -> LessonOutcome | None:
        if not prepared.usable:
            return None
        lesson = self._build_template(record.age_band, record.subject, prepared.usable[0])
        if lesson is None:
            return None
        return LessonOutcome(
            status="ready",
            lesson=lesson,
            source="safe_template",
            label=SAFE_TEMPLATE_LABEL,
            attempts=attempts,
            warnings=prepared.warnings,
        )

    @staticmethod
    def _model_failure(code: str, attempts: int, warnings: list[str]) -> LessonOutcome:
        return LessonOutcome(
            status="failed",
            error_code=code,
            options=(OPTION_RETRY, OPTION_SAFE_TEMPLATE),
            attempts=attempts,
            warnings=warnings,
        )

    @staticmethod
    def _failure(
        code: str,
        *,
        attempts: int,
        warnings: list[str],
        options: tuple[str, ...],
        reasons: list[str] | None = None,
    ) -> LessonOutcome:
        return LessonOutcome(
            status="failed",
            error_code=code,
            options=options,
            attempts=attempts,
            warnings=warnings,
            gate_reasons=reasons or [],
        )

    # -- persistence --------------------------------------------------------------------------

    def _persist(self, session_id: str, outcome: LessonOutcome) -> LessonOutcome:
        """Conditional write GENERATING -> READY / FAILED; never overwrite a Stop (R-08.3)."""
        now = self._clock.now()
        for _ in range(3):
            current = self._store.get(session_id, now)
            if current.state != SessionState.GENERATING.value or outcome.status == "stopped":
                return LessonOutcome(status="stopped", attempts=outcome.attempts)
            if outcome.status == "ready":
                target = SessionState.READY
                update: dict[str, object] = {"lesson": outcome.lesson}
            else:
                target = SessionState.FAILED  # no Lesson stored on failure
                update = {}
            validate_transition(SessionState.GENERATING, target)
            update.update({"state": target.value, "updated_at": now})
            try:
                self._store.put_if_version(current.model_copy(update=update), current.version)
            except VersionConflict:
                continue
            return outcome
        return LessonOutcome(status="stopped", attempts=outcome.attempts)

    # -- helpers ------------------------------------------------------------------------------

    def _prepare(self, record: SessionRecord) -> _Prepared:
        """Apply hazard exclusion, ambiguity labels and PII redaction before any model call."""
        hazards = handle_hazards(ObjectInventory(items=record.objects))
        inventory = label_ambiguous(hazards.inventory)
        items: list[ObjectItem] = []
        warnings: list[str] = []
        for item in inventory.items:
            if item.excluded_reason is not None:
                items.append(item)
                continue
            try:
                result = redact_pii(item.original)
            except PiiNotRedactableError as exc:
                raise PiiRemovalRequired(exc.message) from exc
            if result.redacted:
                if result.warning and result.warning not in warnings:
                    warnings.append(result.warning)
                item = item.model_copy(
                    update={"original": result.text[:50], "normalized": _norm(result.text)[:50]}
                )
            items.append(item)
        usable = [i.original for i in items if i.excluded_reason is None]
        if not usable:
            raise NoUsableObjects
        return _Prepared(
            inventory=ObjectInventory(items=items),
            usable=usable,
            warnings=warnings,
            notices=hazards.notices,
        )


class _PersistingEmitter:
    """Stage emitter that appends each sanitized event to the Session as it happens (R-04.5)."""

    def __init__(self, store: SessionStore, session_id: str, clock: Clock) -> None:
        self._store = store
        self._session_id = session_id
        self._clock = clock

    def __call__(
        self,
        stage: str,
        specialist: str,
        status: Literal["started", "completed", "failed"],
        contract_version: str | None = None,
    ) -> AgentStageEvent:
        now: datetime = self._clock.now()
        event = AgentStageEvent(
            stage=stage,
            specialist=specialist,
            status=status,
            contract_version=contract_version,
            timestamp=now,
        )
        for _ in range(3):
            current = self._store.get(self._session_id, now)
            if current.state != SessionState.GENERATING.value:
                break
            updated = current.model_copy(
                update={"stage_events": [*current.stage_events, event], "updated_at": now}
            )
            try:
                self._store.put_if_version(updated, current.version)
            except VersionConflict:
                continue
            break
        return event


def _window(settings: Settings) -> timedelta:
    return timedelta(hours=settings.idempotency_window_hours)


def _gate(lesson: Lesson, prepared: _Prepared, record: SessionRecord) -> GateResult:
    """Run every Validation_Gate plus the submitted-inputs subset check (R-03.1, R-03.3)."""
    result = check_lesson(lesson, prepared.inventory, record.age_band, record.subject)
    reasons = list(result.reasons)
    try:
        lesson.check_inputs(prepared.usable)
    except ValueError as exc:
        reasons.append(str(exc))
    return GateResult(passed=not reasons, reasons=reasons)
