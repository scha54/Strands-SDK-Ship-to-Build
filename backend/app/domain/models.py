"""Pydantic domain models and Specialist_Contracts (R-01.4, R-03.1, R-03.2, R-04.3, R-06.1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CONTRACT_VERSION = "1.0"


class AgeBand(StrEnum):
    B6_8 = "6-8"
    B9_10 = "9-10"
    B11_12 = "11-12"


class Subject(StrEnum):
    ARITHMETIC = "arithmetic_counting"
    MEASUREMENT = "intro_measurement"


class AssessmentStatus(StrEnum):
    CORRECT = "correct"
    PARTIAL = "partially_correct"
    SUPPORT = "needs_support"
    UNASSESSABLE = "unassessable"


ObjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class CreateSessionRequest(BaseModel):
    """Session creation input; unknown (identity) fields are rejected (R-01.4)."""

    model_config = ConfigDict(extra="forbid")

    age_band: AgeBand
    subject: Subject
    objects: list[ObjectName] = Field(min_length=1, max_length=20)
    language: Literal["en", "hi"] = "en"


class ObjectItem(BaseModel):
    original: str = Field(max_length=50)
    normalized: str = Field(max_length=50)
    assumption: str | None = Field(default=None, max_length=100)
    excluded_reason: str | None = None
    safe_alternative: str | None = None


class ObjectInventory(BaseModel):
    items: list[ObjectItem] = Field(min_length=1, max_length=20)

    def normalized_names(self) -> set[str]:
        return {i.normalized for i in self.items}


class Activity(BaseModel):
    id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=300)
    facilitator_note: str = Field(max_length=600)
    required_objects: list[str] = Field(max_length=10)
    answer_kind: Literal["integer", "decimal", "short_text", "choice"]
    expected_answer: str = Field(max_length=250)
    rubric: str = Field(max_length=500)
    hints: list[str] = Field(min_length=1, max_length=3)
    difficulty: int = Field(ge=1, le=3)
    spelling_matters: bool = False
    alternatives: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str = Field(min_length=1)
    topic: str
    prompt: str = Field(max_length=300)
    scale_max: int = Field(ge=1, le=10)


class Lesson(BaseModel):
    schema_version: str = "1.0"
    source: Literal["generated", "safe_template", "demo_fallback"]
    title: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=200)
    objects: list[str] = Field(min_length=1, max_length=10)
    setup: str = Field(min_length=1, max_length=500)
    activities: list[Activity] = Field(min_length=3, max_length=3)
    baseline_question: Question
    end_question: Question
    estimated_minutes: int = Field(ge=5, le=10)

    @model_validator(mode="after")
    def _unique_activity_ids(self) -> Lesson:
        ids = [a.id for a in self.activities]
        if len(set(ids)) != len(ids):
            raise ValueError("activity ids must be unique")
        return self

    def check_grounding(self, inventory: ObjectInventory) -> None:
        """Every Activity's required_objects must be in the inventory (R-03.1)."""
        allowed = inventory.normalized_names()
        for a in self.activities:
            missing = [o for o in a.required_objects if _norm(o) not in allowed]
            if missing:
                raise ValueError(f"activity {a.id} requires objects not in inventory: {missing}")

    def check_inputs(self, submitted: Iterable[str]) -> None:
        """Lesson objects must be a subset of the Facilitator's submitted inputs (R-03.1)."""
        allowed = {_norm(o) for o in submitted}
        missing = [o for o in self.objects if _norm(o) not in allowed]
        if missing:
            raise ValueError(f"lesson objects not in submitted inputs: {missing}")


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


class Assessment(BaseModel):
    status: AssessmentStatus
    explanation: str = Field(max_length=300)
    misconception: str | None = Field(default=None, max_length=250)
    suggested_scaffold: str | None = Field(default=None, max_length=350)
    confidence: float = Field(ge=0, le=1)
    adjustment_note: str | None = None


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=2000)


class GateResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class Grade(BaseModel):
    status: AssessmentStatus
    explanation: str = Field(max_length=300)


class AgentStageEvent(BaseModel):
    stage: str
    specialist: str
    status: Literal["started", "completed", "failed"]
    contract_version: str | None = None
    timestamp: datetime


class SessionSummary(BaseModel):
    concepts_practiced: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    baseline: int | None = None
    end_answer: int | None = None
    difference: int | None = None
    baseline_skipped: bool = False
    end_skipped: bool = False
    provisional_estimate: str | None = None
    warning: str | None = None


class ApiError(BaseModel):
    code: str
    message: str
    correlation_id: str
    details: dict[str, Any] | list[Any] | None = None


# --- Persisted session record (R-10.1, R-10.2) ----------------------------------------------


class ActivityStatus(BaseModel):
    """Per-Activity progress: status plus attempt and clarification counts (R-05)."""

    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1)
    status: Literal["pending", "completed", "skipped"] = "pending"
    attempts: int = Field(default=0, ge=0)
    clarifications: int = Field(default=0, ge=0)
    hints_used: int = Field(default=0, ge=0)
    assessment: AssessmentStatus | None = None
    excluded: bool = False


class AnswerEntry(BaseModel):
    """A stored answer. Session data only; never logged (R-10.2, R-10.3)."""

    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1)
    answer: str = Field(max_length=2000)


class IdempotencyRecord(BaseModel):
    """Idempotency record retained within the 24 h window (R-11.2, R-11.7)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    route: str = Field(min_length=1)
    payload_hash: str = Field(min_length=1)
    result_ref: str | None = None
    created_at: datetime


class SessionRecord(BaseModel):
    """The persisted Session. Stores only the attributes permitted by R-10.1.

    No child name, birthday, address, school or email; no cross-session link; no
    raw images (R-10.2). ``extra="forbid"`` makes any attempt to carry a forbidden
    attribute a validation error rather than a silent persist.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    token_hash: str = Field(min_length=1)
    state: str = Field(min_length=1)
    age_band: AgeBand
    subject: Subject
    language: Literal["en", "hi"] = "en"
    objects: list[ObjectItem] = Field(default_factory=list)
    lesson: Lesson | None = None
    activity_status: list[ActivityStatus] = Field(default_factory=list)
    answers: list[AnswerEntry] = Field(default_factory=list)
    baseline: int | None = None
    end_answer: int | None = None
    current_index: int = Field(default=0, ge=0)
    stage_events: list[AgentStageEvent] = Field(default_factory=list)
    idempotency: list[IdempotencyRecord] = Field(default_factory=list)
    generation_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    version: int = Field(default=0, ge=0)


# --- Versioned Specialist_Contracts (R-04.3) -------------------------------------------------


class _Contract(BaseModel):
    contract_version: str = CONTRACT_VERSION


class EnvironmentOutput(_Contract):
    inventory: ObjectInventory


class CurriculumPlan(_Contract):
    objective: str = Field(min_length=1, max_length=200)
    age_band: AgeBand
    subject: Subject
    progression: list[str] = Field(min_length=1, max_length=3)


class StoryDraft(_Contract):
    title: str = Field(min_length=1, max_length=80)
    setup: str = Field(min_length=1, max_length=500)
    activities: list[Activity] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _unique_activity_ids(self) -> StoryDraft:
        ids = [a.id for a in self.activities]
        if len(set(ids)) != len(ids):
            raise ValueError("activity ids must be unique")
        return self


class AssessmentOutput(_Contract):
    assessment: Assessment
