"""Composite Validation_Gates: schema, grounding, safety, age vocabulary, readability.

Covers R-03.3, R-08.1, R-08.2, R-08.5, R-09.6; NFR-02, NFR-10. A failure in any Activity
fails the whole Lesson, which the caller counts as one failed attempt (R-08.2).
"""

from __future__ import annotations

from pydantic import ValidationError

from app.domain.models import Activity, AgeBand, GateResult, Lesson, ObjectInventory, Subject
from app.services import grounding
from app.services.age_vocab import check_lesson_vocab
from app.services.readability import check_readability
from app.services.safety import check_activity_safety, check_lesson_safety


def _dedupe(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def check_schema(lesson: Lesson) -> GateResult:
    """Re-validate the Lesson against its schema, including unique Activity IDs (R-03.1)."""
    try:
        Lesson.model_validate(lesson.model_dump())
    except ValidationError as exc:
        return GateResult(passed=False, reasons=[f"schema: {e['msg']}" for e in exc.errors()])
    return GateResult(passed=True)


def check_activity(a: Activity, inv: ObjectInventory) -> GateResult:
    """Grounding, safety and readability gates for one Activity."""
    reasons: list[str] = []
    reasons.extend(grounding.check_activity(a, inv).reasons)
    reasons.extend(check_activity_safety(a).reasons)
    reasons.extend(f"activity {a.id} {r}" for r in check_readability(a.instruction).reasons)
    reasons = _dedupe(reasons)
    return GateResult(passed=not reasons, reasons=reasons)


def check_lesson(
    lesson: Lesson, inv: ObjectInventory, age: AgeBand, subject: Subject
) -> GateResult:
    """All gates for a Lesson; one failing Activity rejects the whole Lesson (R-08.2)."""
    reasons: list[str] = []
    reasons.extend(check_schema(lesson).reasons)
    reasons.extend(grounding.check_lesson(lesson, inv).reasons)
    reasons.extend(check_lesson_safety(lesson).reasons)
    reasons.extend(check_lesson_vocab(lesson, age, subject).reasons)
    for a in lesson.activities:
        reasons.extend(f"activity {a.id} {r}" for r in check_readability(a.instruction).reasons)
    reasons = _dedupe(reasons)
    return GateResult(passed=not reasons, reasons=reasons)


class ValidationGates:
    """Object form of the ValidationGates protocol from the design."""

    def check_lesson(
        self, lesson: Lesson, inv: ObjectInventory, age: AgeBand, subject: Subject
    ) -> GateResult:
        return check_lesson(lesson, inv, age, subject)

    def check_activity(self, a: Activity, inv: ObjectInventory) -> GateResult:
        return check_activity(a, inv)
