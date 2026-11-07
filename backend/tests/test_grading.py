"""Unit tests for the deterministic grader.

Covers R-05.2, R-06.3, R-06.5, R-09.9; NFR-02.
"""

from typing import Any

from app.domain.models import Activity, AssessmentStatus
from app.services.grading import DeterministicGrader, edit_distance, grade


def _activity(kind: str, expected: str, **kw: Any) -> Activity:
    return Activity(
        id="a1",
        instruction="Do it.",
        facilitator_note="Note.",
        required_objects=[],
        answer_kind=kind,
        expected_answer=expected,
        rubric="Rubric.",
        hints=["Hint."],
        difficulty=1,
        **kw,
    )


def test_numeric_is_deterministic_for_repeated_inputs() -> None:
    """R-05.2, NFR-02: repeated identical inputs give equal results."""
    act = _activity("integer", "5")
    results = [grade(act, "5", False) for _ in range(5)]
    assert all(r == results[0] for r in results)
    assert results[0] is not None and results[0].status == AssessmentStatus.CORRECT


def test_numeric_correct_and_wrong() -> None:
    """R-05.2: numbers are parsed and compared, including decimals."""
    g = grade(_activity("decimal", "2.5"), "2.50", False)
    assert g is not None and g.status == AssessmentStatus.CORRECT
    g = grade(_activity("integer", "5"), "I counted 5 apples", False)
    assert g is not None and g.status == AssessmentStatus.CORRECT
    g = grade(_activity("integer", "5"), "6", False)
    assert g is not None and g.status == AssessmentStatus.SUPPORT


def test_ambiguous_numeric_is_unassessable() -> None:
    """R-06.3: unclear answers are never marked wrong."""
    for text in ("maybe", "4 or 5", "   "):
        g = grade(_activity("integer", "5"), text, False)
        assert g is not None and g.status == AssessmentStatus.UNASSESSABLE


def test_two_edit_misspelling_is_correct_when_spelling_does_not_matter() -> None:
    """R-09.9: up to 2 edits per word are tolerated."""
    act = _activity("short_text", "triangle shape")
    g = grade(act, "triangel shaep", False)
    assert g is not None and g.status == AssessmentStatus.CORRECT
    g = grade(act, "triangxxx shape", False)
    assert g is not None and g.status == AssessmentStatus.SUPPORT


def test_no_tolerance_when_spelling_matters() -> None:
    """R-09.9: exact words are required when spelling matters."""
    act = _activity("short_text", "triangle")
    g = grade(act, "triangel", True)
    assert g is not None and g.status == AssessmentStatus.SUPPORT
    g = grade(act, "Triangle", True)
    assert g is not None and g.status == AssessmentStatus.CORRECT


def test_alternatives_accepted() -> None:
    """R-05.2: listed alternatives are accepted."""
    act = _activity("choice", "red", alternatives=["crimson"])
    g = grade(act, "crimson", True)
    assert g is not None and g.status == AssessmentStatus.CORRECT


def test_none_only_for_free_form() -> None:
    """R-06.5: None only when no deterministic verdict exists."""
    free = _activity("short_text", "the block is longer because it has more units in a row")
    assert grade(free, "it is long", False) is None
    for act, ans in (
        (_activity("integer", "3"), "x"),
        (_activity("short_text", "cat"), "dog"),
        (_activity("choice", "a"), "b"),
    ):
        assert grade(act, ans, False) is not None


def test_protocol_class_delegates() -> None:
    """NFR-02: the class form matches the function."""
    act = _activity("integer", "2")
    assert DeterministicGrader().grade(act, "2", False) == grade(act, "2", False)


def test_edit_distance() -> None:
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("", "ab") == 2
