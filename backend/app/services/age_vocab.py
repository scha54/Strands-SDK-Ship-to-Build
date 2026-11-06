"""Age_Band and Subject vocabulary and concept rules (R-03.3; NFR-10).

Each Age_Band and Subject defines out-of-scope terms and a largest whole number a Lesson
may use. Out-of-scope vocabulary in any learner or facilitator field fails the gate.
"""

from __future__ import annotations

import re

from app.domain.models import Activity, AgeBand, GateResult, Lesson, Subject
from app.services.safety import activity_fields

_ADVANCED_ALL = (
    "algebra",
    "algebraic",
    "calculus",
    "equation",
    "equations",
    "variable",
    "exponent",
    "exponents",
    "logarithm",
    "trigonometry",
    "polynomial",
    "quadratic",
    "derivative",
)
_UPPER_PRIMARY = ("percent", "percentage", "ratio", "ratios", "decimal", "decimals")
_MIDDLE = ("fraction", "fractions", "multiplication", "division", "multiply", "divide")

# Terms that are out of scope for each Age_Band.
BAND_OUT_OF_SCOPE: dict[AgeBand, frozenset[str]] = {
    AgeBand.B6_8: frozenset(_ADVANCED_ALL + _UPPER_PRIMARY + _MIDDLE + ("perimeter", "area")),
    AgeBand.B9_10: frozenset(_ADVANCED_ALL + _UPPER_PRIMARY),
    AgeBand.B11_12: frozenset(_ADVANCED_ALL),
}

# Terms that are out of scope for each Subject.
SUBJECT_OUT_OF_SCOPE: dict[Subject, frozenset[str]] = {
    Subject.ARITHMETIC: frozenset(
        {
            "kilogram",
            "kilograms",
            "litre",
            "litres",
            "liter",
            "liters",
            "centimetre",
            "centimetres",
            "centimeter",
            "centimeters",
            "metre",
            "metres",
            "meter",
            "meters",
        }
    ),
    Subject.MEASUREMENT: frozenset({"subtraction", "addition", "multiply", "divide"}),
}

# Largest whole number allowed in learner/facilitator text for each Age_Band.
MAX_NUMBER: dict[AgeBand, int] = {AgeBand.B6_8: 100, AgeBand.B9_10: 1000, AgeBand.B11_12: 10000}

_WORD = re.compile(r"[a-z]+")
_NUMBER = re.compile(r"\b\d[\d,]*\b")


def check_text_vocab(text: str, age: AgeBand, subject: Subject) -> list[str]:
    """Return out-of-scope vocabulary and number findings for ``text``."""
    findings: list[str] = []
    words = set(_WORD.findall(text.casefold()))
    banned = BAND_OUT_OF_SCOPE[age] | SUBJECT_OUT_OF_SCOPE[subject]
    for term in sorted(words & banned):
        findings.append(f"term '{term}' is outside Age_Band {age.value} / {subject.value}")
    for raw in _NUMBER.findall(text):
        value = int(raw.replace(",", ""))
        if value > MAX_NUMBER[age]:
            findings.append(f"number {value} exceeds {MAX_NUMBER[age]} for Age_Band {age.value}")
    return findings


def check_activity_vocab(activity: Activity, age: AgeBand, subject: Subject) -> GateResult:
    reasons: list[str] = []
    for text in activity_fields(activity):
        for finding in check_text_vocab(text, age, subject):
            reason = f"activity {activity.id} {finding}"
            if reason not in reasons:
                reasons.append(reason)
    return GateResult(passed=not reasons, reasons=reasons)


def check_lesson_vocab(lesson: Lesson, age: AgeBand, subject: Subject) -> GateResult:
    """Vocabulary and concept gate for a whole Lesson (R-03.3)."""
    reasons: list[str] = []
    for text in (lesson.title, lesson.objective, lesson.setup):
        for finding in check_text_vocab(text, age, subject):
            reason = f"lesson {finding}"
            if reason not in reasons:
                reasons.append(reason)
    for activity in lesson.activities:
        reasons.extend(check_activity_vocab(activity, age, subject).reasons)
    return GateResult(passed=not reasons, reasons=reasons)
