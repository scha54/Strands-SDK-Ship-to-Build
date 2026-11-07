"""Assessment service: grading, clarification and adaptation.

Covers R-04.2, R-06.1, R-06.2, R-06.3, R-06.4, R-06.6; NFR-09, NFR-10.

* The deterministic grader runs first. The Assessment_Specialist is invoked only when the
  grader has no verdict (R-04.2, R-06.5).
* Exactly one Assessment_Status is returned with an explanation of at most 300 characters,
  shortened further for younger Age_Bands (R-06.1). Specialist output is untrusted: it is
  clamped, and any diagnostic wording is replaced (NFR-10, R-06.6).
* An unassessable answer is never marked incorrect. The first two unclear answers request
  clarification. The third stays ``unassessable``, offers skip or hint and is excluded from
  mastery estimates (R-06.3, R-06.4).
* On a misconception the adapted Activity keeps the objective, the answer and the required
  objects, changes the scaffold level or difficulty, passes every gate, and the change is
  reported to the Facilitator in ``adjustment_note`` (R-06.2).
* Mastery estimates are always labeled provisional, with no diagnosis and no efficacy claims
  (R-06.6, NFR-09).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.domain.models import (
    Activity,
    AgeBand,
    Assessment,
    AssessmentStatus,
    GateResult,
    Grade,
    ObjectInventory,
)
from app.services import gates, grading

MAX_EXPLANATION_CHARS = 300
MAX_CLARIFICATIONS = 2
MAX_HINTS = 3
PROVISIONAL_LABEL = "provisional"

_AGE_EXPLANATION_CAP = {AgeBand.B6_8: 160, AgeBand.B9_10: 240, AgeBand.B11_12: 300}

CLARIFICATION_PROMPT = "I could not tell what you meant. Can you say your answer again?"
EXCLUDED_EXPLANATION = (
    "I still could not tell your answer, so I will not count it. You can skip or ask for a hint."
)
NEUTRAL_EXPLANATION = "Thank you for trying. Let's look at this one together."

# Diagnostic or labeling language that must never reach the Facilitator or Learner (R-06.6).
_DIAGNOSTIC = re.compile(
    r"diagnos|dyslexi|dyscalculi|dysgraphi|adhd|attention deficit|autis|disorder|disabilit|"
    r"impairment|syndrome|learning difficult|learning problem|special needs|"
    r"developmental delay|slow learner|clinical",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

Assessor = Callable[[Activity, str], Awaitable[Assessment]]
ActivityGate = Callable[[Activity, ObjectInventory], GateResult]


def contains_diagnostic_language(text: str) -> bool:
    return bool(_DIAGNOSTIC.search(text))


def _clean(text: str | None, cap: int) -> str | None:
    """Drop diagnostic text and clamp to ``cap`` characters, ending on a sentence if possible."""
    if text is None:
        return None
    text = " ".join(text.split())
    if not text or contains_diagnostic_language(text):
        return None
    if len(text) <= cap:
        return text
    kept = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > cap:
            break
        kept = candidate
    return kept or text[:cap].rstrip()


def _explanation(text: str, age: AgeBand) -> str:
    cap = min(MAX_EXPLANATION_CHARS, _AGE_EXPLANATION_CAP[age])
    return _clean(text, cap) or NEUTRAL_EXPLANATION


@dataclass(frozen=True)
class AssessmentResult:
    """One assessment outcome for one submitted answer."""

    assessment: Assessment
    used_specialist: bool
    clarification_requested: bool = False
    clarification_prompt: str | None = None
    clarifications_used: int = 0
    offer_skip_or_hint: bool = False
    excluded_from_mastery: bool = False
    marked_incorrect: bool = False
    objective: str | None = None
    adapted_activity: Activity | None = None


@dataclass(frozen=True)
class MasteryObservation:
    status: AssessmentStatus
    excluded: bool = False


def provisional_mastery_estimate(observations: Sequence[MasteryObservation]) -> str:
    """A label-first estimate. Excluded and unassessable answers are not counted (R-06.4)."""
    counted = [
        o for o in observations if not o.excluded and o.status != AssessmentStatus.UNASSESSABLE
    ]
    if not counted:
        return "Provisional estimate: not enough answers yet to say."
    right = sum(1 for o in counted if o.status == AssessmentStatus.CORRECT)
    return (
        f"Provisional estimate: {right} of {len(counted)} answers were fully correct so far. "
        "This is a rough guide for this lesson only."
    )


class AssessmentService:
    def __init__(
        self,
        assessor: Assessor,
        *,
        grade_fn: Callable[[Activity, str, bool], Grade | None] = grading.grade,
        activity_gate: ActivityGate = gates.check_activity,
    ) -> None:
        self._assessor = assessor
        self._grade = grade_fn
        self._gate = activity_gate

    async def assess(
        self,
        activity: Activity,
        answer: str,
        age_band: AgeBand,
        *,
        prior_clarifications: int = 0,
        objective: str | None = None,
        inventory: ObjectInventory,
    ) -> AssessmentResult:
        """Assess one answer. ``prior_clarifications`` counts earlier unclear answers."""
        verdict = self._grade(activity, answer, activity.spelling_matters)
        used_specialist = verdict is None
        if verdict is not None:
            raw = Assessment(status=verdict.status, explanation=verdict.explanation, confidence=1.0)
        else:
            raw = await self._assessor(activity, answer)

        explanation = _explanation(raw.explanation, age_band)
        if raw.status == AssessmentStatus.UNASSESSABLE:
            return self._unassessable(
                raw, used_specialist, prior_clarifications, objective, age_band
            )

        misconception = _clean(raw.misconception, 250)
        scaffold = _clean(raw.suggested_scaffold, 350)
        assessment = Assessment(
            status=raw.status,
            explanation=explanation,
            misconception=misconception,
            suggested_scaffold=scaffold,
            confidence=raw.confidence,
        )
        adapted: Activity | None = None
        if misconception and raw.status != AssessmentStatus.CORRECT:
            adapted, note = self._adapt(activity, scaffold, inventory)
            assessment = assessment.model_copy(update={"adjustment_note": note})
        return AssessmentResult(
            assessment=assessment,
            used_specialist=used_specialist,
            objective=objective,
            adapted_activity=adapted,
            marked_incorrect=assessment.status == AssessmentStatus.SUPPORT,
        )

    def _unassessable(
        self,
        raw: Assessment,
        used_specialist: bool,
        prior: int,
        objective: str | None,
        age: AgeBand,
    ) -> AssessmentResult:
        if prior < MAX_CLARIFICATIONS:
            text = _explanation(raw.explanation, age) if used_specialist else CLARIFICATION_PROMPT
            assessment = Assessment(
                status=AssessmentStatus.UNASSESSABLE,
                explanation=_explanation(text, age),
                confidence=raw.confidence,
            )
            return AssessmentResult(
                assessment=assessment,
                used_specialist=used_specialist,
                clarification_requested=True,
                clarification_prompt=CLARIFICATION_PROMPT,
                clarifications_used=prior + 1,
                objective=objective,
            )
        assessment = Assessment(
            status=AssessmentStatus.UNASSESSABLE,
            explanation=_explanation(EXCLUDED_EXPLANATION, age),
            confidence=raw.confidence,
        )
        return AssessmentResult(
            assessment=assessment,
            used_specialist=used_specialist,
            clarifications_used=prior,
            offer_skip_or_hint=True,
            excluded_from_mastery=True,
            objective=objective,
        )

    def _adapt(
        self, activity: Activity, scaffold: str | None, inventory: ObjectInventory
    ) -> tuple[Activity | None, str]:
        """Same objective and answer; lower difficulty, or add scaffold at the lowest level."""
        update: dict[str, object] = {}
        if activity.difficulty > 1:
            update["difficulty"] = activity.difficulty - 1
            change = "made the next step a little easier"
        elif scaffold:
            update["hints"] = [scaffold, *activity.hints][:MAX_HINTS]
            change = "added a gentler hint to the next step"
        else:
            return None, "No change to the next step was needed."
        candidate = activity.model_copy(update=update)
        if not self._gate(candidate, inventory).passed:
            return None, "The next step stays as planned; the adjusted version was not used."
        return candidate, f"The lesson goal stays the same. We {change}."
