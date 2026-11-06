"""Unit tests for safety, age vocabulary, readability and composite Validation_Gates.

Covers R-03.3, R-08.1, R-08.2, R-08.5, R-09.6; NFR-02, NFR-10.
"""

import pytest
from app.domain.models import Activity, AgeBand, Lesson, Question, Subject
from app.services.age_vocab import check_text_vocab
from app.services.gates import ValidationGates, check_activity, check_lesson
from app.services.normalizer import normalize_objects
from app.services.readability import check_readability

INV = normalize_objects(["stone", "leaf"])


def _activity(
    aid: str, instruction: str = "Count the stones. Tell me how many.", **kw: object
) -> Activity:
    data: dict[str, object] = {
        "id": aid,
        "instruction": instruction,
        "facilitator_note": "Guide gently.",
        "required_objects": ["stone"],
        "answer_kind": "integer",
        "expected_answer": "3",
        "rubric": "Counts correctly.",
        "hints": ["Count slowly."],
        "difficulty": 1,
    }
    data.update(kw)
    return Activity.model_validate(data)


def _lesson(activities: list[Activity] | None = None) -> Lesson:
    q = Question(id="q", topic="count", prompt="How many?", scale_max=5)
    return Lesson(
        source="generated",
        title="Stone counting",
        objective="Count up to ten",
        objects=["stone"],
        setup="Put the stones on the floor.",
        activities=activities or [_activity(f"a{i}") for i in range(3)],
        baseline_question=q,
        end_question=q,
        estimated_minutes=5,
    )


def _check(lesson: Lesson):  # type: ignore[no-untyped-def]
    return check_lesson(lesson, INV, AgeBand.B6_8, Subject.ARITHMETIC)


def test_clean_lesson_passes_all_gates() -> None:
    """R-03.3, R-08.1, R-09.6: a clean Lesson passes every gate."""
    result = _check(_lesson())
    assert result.passed, result.reasons
    assert ValidationGates().check_lesson(_lesson(), INV, AgeBand.B6_8, Subject.ARITHMETIC).passed
    assert check_activity(_activity("a1"), INV).passed


HAZARDS = {
    "ingestion": "Taste the berries.",
    "sharp": "Cut the paper with a knife.",
    "fire": "Light a candle and count.",
    "electricity": "Plug the cable in.",
    "chemicals": "Smell the bleach.",
    "heights": "Climb the ladder.",
    "strangers": "Ask a stranger for help.",
    "water": "Walk to the river.",
}


@pytest.mark.parametrize("text", list(HAZARDS.values()), ids=list(HAZARDS))
def test_each_hazard_category_rejects_whole_lesson(text: str) -> None:
    """R-08.1, R-08.2: one hazardous Activity rejects the whole Lesson."""
    acts = [_activity("a0"), _activity("a1", facilitator_note=text), _activity("a2")]
    result = _check(_lesson(acts))
    assert not result.passed
    assert any("a1" in r for r in result.reasons)
    assert not check_activity(acts[1], INV).passed


@pytest.mark.parametrize(
    "text",
    ["Keep this a secret from your parents.", "Don't tell your teacher.", "I'm your best friend."],
)
def test_secrecy_and_dependence_reject_lesson(text: str) -> None:
    """R-08.5: secrecy or emotional-dependence phrases reject the Lesson."""
    acts = [_activity("a0"), _activity("a1"), _activity("a2", hints=[text])]
    assert not _check(_lesson(acts)).passed


def test_overlong_instructions_fail_readability() -> None:
    """R-09.6: over 3 sentences or over 25 words per sentence fails."""
    assert not check_readability("One. Two. Three. Four.").passed
    long_sentence = " ".join(["stone"] * 26) + "."
    assert not check_readability(long_sentence).passed
    assert not _check(
        _lesson([_activity("a0", long_sentence), _activity("a1"), _activity("a2")])
    ).passed


def test_high_reading_grade_fails_readability() -> None:
    """R-09.6: text above grade 6 fails."""
    hard = "Understanding mathematical relationships necessitates extraordinary concentration."
    assert not check_readability(hard).passed
    assert check_readability("Count the stones. Say the number.").passed


def test_age_vocab_rules() -> None:
    """R-03.3: out-of-scope terms and numbers fail by Age_Band and Subject."""
    assert check_text_vocab("Add the fractions.", AgeBand.B6_8, Subject.ARITHMETIC)
    assert not check_text_vocab("Add the fractions.", AgeBand.B11_12, Subject.ARITHMETIC)
    assert check_text_vocab("Count to 500.", AgeBand.B6_8, Subject.ARITHMETIC)
    assert check_text_vocab("Weigh in kilograms.", AgeBand.B9_10, Subject.ARITHMETIC)
    lesson = _lesson([_activity("a0", "Solve the equation."), _activity("a1"), _activity("a2")])
    assert not _check(lesson).passed


def test_grounding_and_schema_gates_compose() -> None:
    """R-08.1, NFR-02: off-inventory objects and duplicate IDs fail the composite gate."""
    off = _activity("a0", required_objects=["tablet"])
    assert not check_activity(off, INV).passed
    dup = _lesson().model_copy(update={"activities": [_activity("x")] * 3})
    result = _check(dup)
    assert not result.passed
    assert any(r.startswith("schema") for r in result.reasons)
