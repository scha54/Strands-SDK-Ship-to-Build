"""Learner and facilitator view projectors (R-03.2, R-03.6, R-03.7, R-05.1; NFR-02).

The projectors build explicit, allow-listed response models from a ``SessionRecord``; they never
dump the stored ``Activity``. This guarantees by construction that:

* the Learner view never carries ``facilitator_note`` (R-03.2);
* ``expected_answer`` and ``rubric`` are omitted while the shown Activity has no submitted
  answer (R-03.6) and included for that Activity only once it has one (R-03.7);
* exactly one Activity is shown, with an "n of N" progress indicator (R-05.1);
* facilitator notes are served only by the facilitator projection of the same session. The
  caller (API layer) authorizes both views with the same Capability_Token check.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.models import Activity, SessionRecord


class Progress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: int
    total: int
    label: str


class LearnerActivity(BaseModel):
    """Allow-listed Learner-facing Activity. Answer fields are None until answered."""

    model_config = ConfigDict(extra="forbid")

    id: str
    instruction: str
    required_objects: list[str]
    answer_kind: str
    difficulty: int
    answered: bool
    expected_answer: str | None = None
    rubric: str | None = None


class LearnerView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str
    setup: str
    source: str
    activity: LearnerActivity | None
    progress: Progress


class FacilitatorView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    activity_id: str | None
    facilitator_note: str | None
    progress: Progress


def _current(record: SessionRecord) -> tuple[Activity | None, Progress]:
    if record.lesson is None:
        raise ValueError("session has no lesson to project")
    activities = record.lesson.activities
    total = len(activities)
    index = record.current_index
    if index >= total:
        return None, Progress(current=total, total=total, label=f"{total} of {total}")
    return activities[index], Progress(
        current=index + 1, total=total, label=f"{index + 1} of {total}"
    )


def project_learner_view(record: SessionRecord) -> LearnerView:
    """Project the Learner view: one Activity, no notes, answers only after submission."""
    activity, progress = _current(record)  # raises ValueError when no lesson
    lesson = record.lesson
    if lesson is None:  # pragma: no cover - _current already guards this
        raise ValueError("session has no lesson to project")
    shown: LearnerActivity | None = None
    if activity is not None:
        answered = any(a.activity_id == activity.id for a in record.answers)
        shown = LearnerActivity(
            id=activity.id,
            instruction=activity.instruction,
            required_objects=list(activity.required_objects),
            answer_kind=activity.answer_kind,
            difficulty=activity.difficulty,
            answered=answered,
            expected_answer=activity.expected_answer if answered else None,
            rubric=activity.rubric if answered else None,
        )
    return LearnerView(
        session_id=record.session_id,
        title=lesson.title,
        setup=lesson.setup,
        source=lesson.source,
        activity=shown,
        progress=progress,
    )


def project_facilitator_view(record: SessionRecord) -> FacilitatorView:
    """Project the Facilitator view: the current Activity's note, for the same session."""
    activity, progress = _current(record)
    return FacilitatorView(
        session_id=record.session_id,
        activity_id=activity.id if activity else None,
        facilitator_note=activity.facilitator_note if activity else None,
        progress=progress,
    )
