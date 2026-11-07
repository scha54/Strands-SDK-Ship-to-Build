"""Deterministic grader (R-05.2, R-06.3, R-06.5, R-09.9; NFR-02).

No model call is made here. Numeric answers are parsed and compared exactly. Text answers
are compared word by word, allowing an edit distance of at most 2 per word unless spelling
matters. ``None`` means no deterministic verdict exists (free-form answers), so the
Assessment_Specialist is invoked.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.domain.models import Activity, AssessmentStatus, Grade

MAX_WORD_EDITS = 2
# Expected answers longer than this are free-form sentences with no single right wording.
MAX_DETERMINISTIC_WORDS = 5

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)")
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)

_CORRECT = Grade(status=AssessmentStatus.CORRECT, explanation="That matches the expected answer.")
_SUPPORT = Grade(
    status=AssessmentStatus.SUPPORT,
    explanation="That does not match the expected answer yet.",
)
_UNCLEAR = Grade(
    status=AssessmentStatus.UNASSESSABLE,
    explanation="The answer is unclear. Please ask the learner to answer again.",
)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _parse_number(text: str) -> Decimal | None | bool:
    """Return the single number in ``text``; None if there is none; False if ambiguous."""
    found = _NUMBER.findall(text.replace(",", ""))
    values: set[Decimal] = set()
    for tok in found:
        try:
            values.add(Decimal(tok))
        except InvalidOperation:  # pragma: no cover - regex only yields valid numbers
            return None
    if not values:
        return None
    if len(values) > 1:
        return False
    return next(iter(values))


def _words_match(given: list[str], target: list[str], tolerance: int) -> bool:
    if len(given) != len(target):
        return False
    return all(edit_distance(g, t) <= tolerance for g, t in zip(given, target, strict=True))


class DeterministicGrader:
    """Implements the ``Grader`` protocol without any model call."""

    def grade(self, activity: Activity, answer: str, spelling_matters: bool) -> Grade | None:
        return grade(activity, answer, spelling_matters)


def grade(activity: Activity, answer: str, spelling_matters: bool) -> Grade | None:
    """Grade ``answer``; ``None`` only when no deterministic verdict exists."""
    if activity.answer_kind in ("integer", "decimal"):
        return _grade_numeric(activity, answer)
    if activity.answer_kind == "short_text" and (
        len(_words(activity.expected_answer)) > MAX_DETERMINISTIC_WORDS
    ):
        return None
    return _grade_text(activity, answer, spelling_matters)


def matches_format(activity: Activity, answer: str) -> bool:
    """Whether ``answer`` has the Activity's expected answer format (R-05.4).

    Numeric Activities need at least one number (several numbers are ambiguous, not malformed,
    and are graded ``unassessable``). Other kinds need at least one word.
    """
    if activity.answer_kind in ("integer", "decimal"):
        return _parse_number(answer) is not None
    return bool(_words(answer))


def _grade_numeric(activity: Activity, answer: str) -> Grade:
    given = _parse_number(answer)
    if not isinstance(given, Decimal):
        return _UNCLEAR
    expected = _parse_number(activity.expected_answer)
    candidates: list[Decimal] = []
    if isinstance(expected, Decimal):
        candidates.append(expected)
    for alt in activity.alternatives:
        parsed = _parse_number(alt)
        if isinstance(parsed, Decimal):
            candidates.append(parsed)
    if not candidates:
        return _UNCLEAR
    if activity.answer_kind == "integer" and given != given.to_integral_value():
        return _SUPPORT
    return _CORRECT if given in candidates else _SUPPORT


def _grade_text(activity: Activity, answer: str, spelling_matters: bool) -> Grade:
    given = _words(answer)
    if not given:
        return _UNCLEAR
    tolerance = 0 if spelling_matters else MAX_WORD_EDITS
    for target_text in [activity.expected_answer, *activity.alternatives]:
        target = _words(target_text)
        if target and _words_match(given, target, tolerance):
            return _CORRECT
    return _SUPPORT
