"""Unit tests for domain models."""

from typing import Any

import pytest
from app.domain.models import (
    Activity,
    AgeBand,
    AnswerRequest,
    Assessment,
    AssessmentOutput,
    AssessmentStatus,
    CreateSessionRequest,
    CurriculumPlan,
    EnvironmentOutput,
    Lesson,
    ObjectInventory,
    ObjectItem,
    StoryDraft,
    Subject,
)
from pydantic import ValidationError


def activity(i: str = "a1", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": i,
        "instruction": "Count the stones.",
        "facilitator_note": "note",
        "required_objects": ["stone"],
        "answer_kind": "integer",
        "expected_answer": "5",
        "rubric": "5 is correct",
        "hints": ["Touch each stone."],
        "difficulty": 1,
    }
    base.update(kw)
    return base


def question(i: str) -> dict[str, Any]:
    return {"id": i, "topic": "counting", "prompt": "How sure are you?", "scale_max": 5}


def lesson(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source": "generated",
        "title": "Stone counting",
        "objective": "Count to ten",
        "objects": ["stone"],
        "setup": "Put stones on the table.",
        "activities": [activity("a1"), activity("a2"), activity("a3")],
        "baseline_question": question("b"),
        "end_question": question("e"),
        "estimated_minutes": 5,
    }
    base.update(kw)
    return base


def inventory() -> ObjectInventory:
    return ObjectInventory(items=[ObjectItem(original="Stone", normalized="stone")])


def test_valid_session_request() -> None:
    """R-01.4: valid request passes."""
    r = CreateSessionRequest.model_validate(
        {"age_band": "6-8", "subject": "arithmetic_counting", "objects": [" stone "]}
    )
    assert r.age_band is AgeBand.B6_8
    assert r.objects == ["stone"]
    assert r.subject is Subject.ARITHMETIC


@pytest.mark.parametrize("field", ["name", "birthday", "address", "school", "email"])
def test_identity_fields_rejected(field: str) -> None:
    """R-01.4, NFR-02: identity fields fail validation."""
    with pytest.raises(ValidationError):
        CreateSessionRequest.model_validate(
            {"age_band": "6-8", "subject": "intro_measurement", "objects": ["a"], field: "x"}
        )


@pytest.mark.parametrize("objects", [[], ["a"] * 21, ["x" * 51], [" "]])
def test_object_bounds(objects: list[str]) -> None:
    """R-02.1 / R-01.4: object count and length bounds."""
    with pytest.raises(ValidationError):
        CreateSessionRequest.model_validate(
            {"age_band": "6-8", "subject": "intro_measurement", "objects": objects}
        )


def test_valid_lesson() -> None:
    """R-03.1, R-03.2: valid lesson passes grounding and input checks."""
    le = Lesson.model_validate(lesson())
    le.check_grounding(inventory())
    le.check_inputs(["Stone"])


@pytest.mark.parametrize(
    "override",
    [
        {"title": "x" * 81},
        {"objective": "x" * 201},
        {"objects": []},
        {"objects": ["o"] * 11},
        {"setup": ""},
        {"estimated_minutes": 4},
        {"estimated_minutes": 11},
        {"activities": [activity("a1"), activity("a2")]},
        {"activities": [activity("a1"), activity("a1"), activity("a3")]},
        {"activities": [activity("a1"), activity("a2"), activity("a3", instruction="x" * 301)]},
        {"activities": [activity("a1"), activity("a2"), activity("a3", hints=[])]},
        {"activities": [activity("a1"), activity("a2"), activity("a3", hints=["h"] * 4)]},
        {"activities": [activity("a1"), activity("a2"), activity("a3", difficulty=4)]},
    ],
)
def test_lesson_bound_violations(override: dict[str, Any]) -> None:
    """R-03.1, R-03.2: bound violations fail."""
    with pytest.raises(ValidationError):
        Lesson.model_validate(lesson(**override))


def test_required_objects_must_be_in_inventory() -> None:
    """R-03.1: ungrounded Activity objects fail."""
    bad = activity("a3", required_objects=["car"])
    le = Lesson.model_validate(lesson(activities=[activity("a1"), activity("a2"), bad]))
    with pytest.raises(ValueError, match="inventory"):
        le.check_grounding(inventory())


def test_lesson_objects_must_be_in_inputs() -> None:
    """R-03.1: Lesson objects outside submitted inputs fail."""
    le = Lesson.model_validate(lesson())
    with pytest.raises(ValueError, match="submitted"):
        le.check_inputs(["leaf"])


def test_assessment_and_answer_bounds() -> None:
    """R-06.1: explanation at most 300 chars; answers 1 to 2000 chars."""
    ok = Assessment(status=AssessmentStatus.CORRECT, explanation="x" * 300, confidence=1)
    assert ok.status is AssessmentStatus.CORRECT
    with pytest.raises(ValidationError):
        Assessment(status=AssessmentStatus.CORRECT, explanation="x" * 301, confidence=0.5)
    with pytest.raises(ValidationError):
        Assessment(status=AssessmentStatus.CORRECT, explanation="x", confidence=1.1)
    with pytest.raises(ValidationError):
        AnswerRequest(answer="")
    with pytest.raises(ValidationError):
        AnswerRequest(answer="x" * 2001)


def test_contracts_carry_version() -> None:
    """R-04.3: each Specialist_Contract carries contract_version."""
    acts = [Activity.model_validate(activity(f"a{i}")) for i in range(3)]
    outs = [
        EnvironmentOutput(inventory=inventory()),
        CurriculumPlan(
            objective="o", age_band=AgeBand.B9_10, subject=Subject.ARITHMETIC, progression=["p"]
        ),
        StoryDraft(title="t", setup="s", activities=acts),
        AssessmentOutput(
            assessment=Assessment(status=AssessmentStatus.PARTIAL, explanation="e", confidence=0.5)
        ),
    ]
    assert all(o.contract_version == "1.0" for o in outs)


def test_story_draft_requires_three_unique_activities() -> None:
    """R-04.3, R-03.1: draft validation."""
    acts = [Activity.model_validate(activity("a")) for _ in range(3)]
    with pytest.raises(ValidationError):
        StoryDraft(title="t", setup="s", activities=acts)
