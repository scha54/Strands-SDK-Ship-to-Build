"""Tests for the learner/facilitator view projectors."""

from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.models import AgeBand, AnswerEntry, Lesson, SessionRecord, Subject
from app.services.learner_view import project_facilitator_view, project_learner_view

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _activity(i: int) -> dict[str, Any]:
    return {
        "id": f"a{i}",
        "instruction": f"Count the stones {i}.",
        "facilitator_note": f"SECRETNOTE{i}",
        "required_objects": ["stone"],
        "answer_kind": "integer",
        "expected_answer": f"EXPECTED{i}",
        "rubric": f"RUBRIC{i}",
        "hints": ["Touch each stone."],
        "difficulty": 1,
    }


def _record(index: int = 0, answered: list[str] | None = None) -> SessionRecord:
    q = {"id": "q", "topic": "t", "prompt": "How sure?", "scale_max": 5}
    lesson = Lesson.model_validate(
        {
            "source": "generated",
            "title": "T",
            "objective": "o",
            "objects": ["stone"],
            "setup": "s",
            "activities": [_activity(i) for i in range(3)],
            "baseline_question": q,
            "end_question": q,
            "estimated_minutes": 5,
        }
    )
    return SessionRecord(
        session_id="s1",
        token_hash="h",  # noqa: S106
        state="in_progress",
        age_band=AgeBand.B6_8,
        subject=Subject.ARITHMETIC,
        lesson=lesson,
        answers=[AnswerEntry(activity_id=a, answer="3") for a in answered or []],
        current_index=index,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW,
    )


def test_no_leak_before_answer() -> None:
    """R-03.2, R-03.6, NFR-02: nothing sensitive serialized before an answer."""
    text = project_learner_view(_record()).model_dump_json()
    for leaked in ("EXPECTED", "RUBRIC", "SECRETNOTE", "facilitator_note"):
        assert leaked not in text


def test_answer_reveals_only_that_activity() -> None:
    """R-03.7: after an answer, only that Activity's answer and rubric appear."""
    text = project_learner_view(_record(answered=["a0"])).model_dump_json()
    assert "EXPECTED0" in text and "RUBRIC0" in text
    assert "EXPECTED1" not in text and "EXPECTED2" not in text
    assert "RUBRIC1" not in text and "SECRETNOTE" not in text


def test_answer_for_other_activity_does_not_reveal_current() -> None:
    """R-03.6: an answer on a different Activity does not unlock the shown one."""
    text = project_learner_view(_record(index=1, answered=["a0"])).model_dump_json()
    assert "EXPECTED" not in text and "RUBRIC" not in text


def test_single_activity_and_progress() -> None:
    """R-05.1: exactly one Activity and an 'n of N' indicator."""
    view = project_learner_view(_record(index=1))
    assert view.activity is not None and view.activity.id == "a1"
    assert view.progress.label == "2 of 3"
    assert "a0" not in view.model_dump_json() and "a2" not in view.model_dump_json()


def test_facilitator_view_serves_note() -> None:
    """R-03.2: notes appear only in the facilitator projection."""
    view = project_facilitator_view(_record(index=2))
    assert view.facilitator_note == "SECRETNOTE2"
    assert view.progress.label == "3 of 3"


def test_completed_lesson_shows_no_activity() -> None:
    """R-05.1: past the last Activity nothing is shown."""
    assert project_learner_view(_record(index=3)).activity is None


def test_missing_lesson_rejected() -> None:
    """Projection requires a Lesson."""
    rec = _record().model_copy(update={"lesson": None})
    with pytest.raises(ValueError):
        project_learner_view(rec)
