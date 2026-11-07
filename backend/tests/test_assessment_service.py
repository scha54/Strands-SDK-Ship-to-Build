"""Unit tests for the assessment service.

Covers R-04.2, R-06.1, R-06.2, R-06.3, R-06.4, R-06.6; NFR-09, NFR-10.
"""

from typing import Any

import pytest
from app.domain.models import Activity, AgeBand, Assessment, AssessmentStatus
from app.services.assessment_service import (
    MAX_EXPLANATION_CHARS,
    AssessmentService,
    MasteryObservation,
    contains_diagnostic_language,
    provisional_mastery_estimate,
)
from app.services.normalizer import normalize_objects

INV = normalize_objects(["stone", "leaf"])


def _activity(kind: str = "integer", expected: str = "3", **kw: Any) -> Activity:
    data: dict[str, Any] = {
        "id": "a1",
        "instruction": "Count the stones. Tell me how many.",
        "facilitator_note": "Guide gently.",
        "required_objects": ["stone"],
        "answer_kind": kind,
        "expected_answer": expected,
        "rubric": "Counts correctly.",
        "hints": ["Count slowly."],
        "difficulty": 2,
    }
    data.update(kw)
    return Activity.model_validate(data)


class FakeAssessor:
    def __init__(self, result: Assessment) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self, activity: Activity, answer: str) -> Assessment:
        self.calls += 1
        return self.result


def _assessment(status: AssessmentStatus, **kw: Any) -> Assessment:
    data: dict[str, Any] = {"status": status, "explanation": "Nice try.", "confidence": 0.8}
    data.update(kw)
    return Assessment.model_validate(data)


FREE_TEXT = "Stones are heavy because they are made of rock and sand today"


async def test_specialist_not_called_for_deterministic_grade() -> None:
    """R-04.2: a deterministic verdict means no specialist call."""
    spec = FakeAssessor(_assessment(AssessmentStatus.CORRECT))
    svc = AssessmentService(spec)
    res = await svc.assess(_activity(), "3", AgeBand.B6_8, inventory=INV)
    assert spec.calls == 0 and not res.used_specialist
    assert res.assessment.status == AssessmentStatus.CORRECT


async def test_specialist_called_when_no_verdict() -> None:
    """R-04.2: free-form answers go to the specialist; one status is returned."""
    spec = FakeAssessor(_assessment(AssessmentStatus.PARTIAL))
    svc = AssessmentService(spec)
    act = _activity("short_text", FREE_TEXT)
    res = await svc.assess(act, "they are hard", AgeBand.B9_10, inventory=INV)
    assert spec.calls == 1 and res.used_specialist
    assert res.assessment.status == AssessmentStatus.PARTIAL


@pytest.mark.parametrize("age", list(AgeBand))
async def test_explanation_at_most_300_chars_and_suited_to_age(age: AgeBand) -> None:
    """R-06.1: long specialist explanations are clamped, shorter for young learners."""
    long = "You counted well. " * 40
    spec = FakeAssessor(_assessment(AssessmentStatus.PARTIAL, explanation=long[:300]))
    svc = AssessmentService(spec)
    act = _activity("short_text", FREE_TEXT)
    res = await svc.assess(act, "x y", age, inventory=INV)
    n = len(res.assessment.explanation)
    assert 0 < n <= MAX_EXPLANATION_CHARS
    if age == AgeBand.B6_8:
        assert n <= 160


async def test_misconception_adapts_and_reports() -> None:
    """R-06.2: objective kept, difficulty lowered, gated, reported to the Facilitator."""
    spec = FakeAssessor(_assessment(AssessmentStatus.SUPPORT, misconception="Skipped one stone."))
    svc = AssessmentService(spec)
    act = _activity("short_text", FREE_TEXT, difficulty=3)
    res = await svc.assess(act, "no idea", AgeBand.B9_10, objective="Count to ten", inventory=INV)
    adapted = res.adapted_activity
    assert adapted is not None
    assert res.objective == "Count to ten"
    assert adapted.difficulty == 2
    assert adapted.expected_answer == act.expected_answer
    assert adapted.required_objects == act.required_objects
    assert (
        res.assessment.adjustment_note and "goal stays the same" in res.assessment.adjustment_note
    )


async def test_adaptation_at_lowest_level_adds_scaffold_hint() -> None:
    """R-06.2: at difficulty 1 the scaffold level changes instead."""
    spec = FakeAssessor(
        _assessment(
            AssessmentStatus.SUPPORT,
            misconception="Lost count.",
            suggested_scaffold="Touch each stone as you count.",
        )
    )
    svc = AssessmentService(spec)
    act = _activity("short_text", FREE_TEXT, difficulty=1)
    res = await svc.assess(act, "um", AgeBand.B9_10, inventory=INV)
    assert res.adapted_activity is not None
    assert res.adapted_activity.hints[0] == "Touch each stone as you count."


async def test_adapted_activity_failing_gates_is_not_used() -> None:
    """R-06.2: an adapted Activity must pass the gates; otherwise it is dropped."""
    spec = FakeAssessor(
        _assessment(
            AssessmentStatus.SUPPORT,
            misconception="Lost count.",
            suggested_scaffold="Light a fire with a match to count.",
        )
    )
    svc = AssessmentService(spec)
    act = _activity("short_text", FREE_TEXT, difficulty=1)
    res = await svc.assess(act, "um", AgeBand.B9_10, inventory=INV)
    assert res.adapted_activity is None
    assert res.assessment.adjustment_note


async def test_unclear_answers_never_marked_wrong_and_third_is_excluded() -> None:
    """R-06.3, R-06.4: two clarifications, then excluded with skip or hint offered."""
    svc = AssessmentService(FakeAssessor(_assessment(AssessmentStatus.CORRECT)))
    act = _activity()
    first = await svc.assess(act, "banana", AgeBand.B6_8, prior_clarifications=0, inventory=INV)
    second = await svc.assess(act, "banana", AgeBand.B6_8, prior_clarifications=1, inventory=INV)
    third = await svc.assess(act, "banana", AgeBand.B6_8, prior_clarifications=2, inventory=INV)
    for r in (first, second):
        assert r.assessment.status == AssessmentStatus.UNASSESSABLE
        assert r.clarification_requested and not r.marked_incorrect
        assert not r.excluded_from_mastery
    assert (first.clarifications_used, second.clarifications_used) == (1, 2)
    assert third.assessment.status == AssessmentStatus.UNASSESSABLE
    assert third.excluded_from_mastery and third.offer_skip_or_hint
    assert not third.clarification_requested and not third.marked_incorrect


async def test_diagnostic_wording_removed_from_specialist_output() -> None:
    """R-06.6, NFR-10: untrusted model output cannot carry diagnostic language."""
    spec = FakeAssessor(
        _assessment(
            AssessmentStatus.SUPPORT,
            explanation="This looks like dyslexia, a learning disorder.",
            misconception="Signs of dyscalculia.",
            suggested_scaffold="Get a diagnosis.",
        )
    )
    svc = AssessmentService(spec)
    act = _activity("short_text", FREE_TEXT)
    res = await svc.assess(act, "x", AgeBand.B11_12, inventory=INV)
    a = res.assessment
    for text in (a.explanation, a.misconception, a.suggested_scaffold, a.adjustment_note):
        assert text is None or not contains_diagnostic_language(text)
    assert res.adapted_activity is None


def test_mastery_estimate_is_provisional_and_excludes_unclear() -> None:
    """R-06.4, R-06.6, NFR-09: provisional label; excluded answers are not counted."""
    obs = [
        MasteryObservation(AssessmentStatus.CORRECT),
        MasteryObservation(AssessmentStatus.SUPPORT),
        MasteryObservation(AssessmentStatus.UNASSESSABLE, excluded=True),
    ]
    text = provisional_mastery_estimate(obs)
    assert text.lower().startswith("provisional")
    assert "1 of 2" in text
    assert not contains_diagnostic_language(text)
    assert "improve" not in text.lower()
    assert provisional_mastery_estimate([]).lower().startswith("provisional")
