"""Equal scoring for answers given via an accessibility alternative (task 10.3).

Covered requirements:

* R-09.8 - an Activity that depends on color, sound or fine motor skills offers an alternative;
  equivalent answers receive the same score and completion status.
* NFR-03 - accessible design: the grader is mode-independent.

The Facilitator-chosen access mode only changes how an Activity is presented; grading takes the
same ``(activity, answer)`` input, so an answer equivalent to the expected answer, including
one declared in ``Activity.alternatives``, yields an identical ``Grade``.
"""

from __future__ import annotations

import pytest
from app.domain.models import Activity, AssessmentStatus
from app.services.grading import grade


def _activity(kind: str, expected: str, alternatives: list[str]) -> Activity:
    return Activity(
        id="a1",
        instruction="Sort the stones, then tell me the answer.",
        facilitator_note="Stay close.",
        required_objects=["stones"],
        answer_kind=kind,
        expected_answer=expected,
        rubric="Counts correctly.",
        hints=["Count slowly."],
        difficulty=1,
        alternatives=alternatives,
    )


@pytest.mark.parametrize(
    ("kind", "expected", "alternatives", "equivalent"),
    [
        ("integer", "4", ["4.0"], "4.0"),
        ("short_text", "round", ["circle"], "circle"),
        ("short_text", "the red stone", ["the big stone"], "the big stone"),
    ],
)
def test_equivalent_alternative_answer_gets_same_score_and_status(
    kind: str, expected: str, alternatives: list[str], equivalent: str
) -> None:
    """R-09.8: the alternative-path answer is graded exactly like the standard one."""
    activity = _activity(kind, expected, alternatives)
    standard = grade(activity, expected, spelling_matters=False)
    via_alternative = grade(activity, equivalent, spelling_matters=False)
    assert standard is not None and via_alternative is not None
    assert standard.status is AssessmentStatus.CORRECT
    assert via_alternative.status == standard.status
    assert via_alternative == standard


def test_wrong_answer_is_not_rewarded_by_the_alternative_path() -> None:
    """R-09.8: equal scoring means equal for wrong answers too."""
    activity = _activity("short_text", "round", ["circle"])
    assert grade(activity, "square", spelling_matters=False) != grade(
        activity, "circle", spelling_matters=False
    )
