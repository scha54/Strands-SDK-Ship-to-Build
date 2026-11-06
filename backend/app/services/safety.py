"""Safety gate: hazard taxonomy plus secrecy and emotional-dependence checks.

Covers R-03.3, R-08.1, R-08.2, R-08.5; NFR-02, NFR-10. Deterministic and model-free.
Every learner and facilitator field of every Activity (and the Lesson title, objective
and setup) is scanned. One hit in any field rejects the whole Lesson (R-08.2).
"""

from __future__ import annotations

import re

from app.domain.models import Activity, GateResult, Lesson

# Hazard category -> regex of concepts that must not appear in learner/facilitator text.
HAZARD_PATTERNS: dict[str, re.Pattern[str]] = {
    "ingestion": re.compile(
        r"\b(eat|eating|ate|taste|tasting|swallow\w*|lick\w*|chew\w*|drink\w*|"
        r"put\s+(?:it|them|\w+)\s+in\s+(?:your|the)\s+mouth|mouth)\b",
        re.IGNORECASE,
    ),
    "sharp objects": re.compile(
        r"\b(knife|knives|scissors|blade\w*|razor\w*|needle\w*|sharp\w*|cut|cuts|cutting|"
        r"slice|slicing|saw|nail|nails)\b",
        re.IGNORECASE,
    ),
    "fire": re.compile(
        r"\b(fire|fires|flame\w*|burn\w*|candle\w*|lighter|matchstick\w*|matchbox\w*|"
        r"(?:light|strike)\s+a\s+match|matches|stove|oven|boil\w*|heat\w*|hot)\b",
        re.IGNORECASE,
    ),
    "electricity": re.compile(
        r"\b(electric\w*|outlet\w*|socket\w*|plug\w*|batter(?:y|ies)|charger\w*|wire|wires|"
        r"cable\w*|power\s+cord)\b",
        re.IGNORECASE,
    ),
    "hazardous chemicals": re.compile(
        r"\b(chemical\w*|bleach|detergent\w*|poison\w*|acid\w*|toxic|cleaner\w*|"
        r"medicine\w*|pills?|paint\s+thinner|petrol|kerosene)\b",
        re.IGNORECASE,
    ),
    "heights": re.compile(
        r"\b(climb\w*|ladder\w*|roof\w*|balcon(?:y|ies)|high\s+shelf|tall\s+tree|"
        r"jump\w*\s+(?:off|from)|stand\w*\s+on\s+a\s+(?:chair|table|stool))\b",
        re.IGNORECASE,
    ),
    "strangers": re.compile(
        r"\b(strangers?|unknown\s+(?:person|people|adult)s?|"
        r"someone\s+you\s+(?:do\s*n[o']t|don't|do\s+not)\s+know|"
        r"meet\s+someone\s+new|go\s+with\s+(?:a|an)\s+adult\s+you)\b",
        re.IGNORECASE,
    ),
    "dangerous water": re.compile(
        r"\b(pool|pools|river\w*|lake\w*|pond\w*|ocean\w*|swim\w*|drown\w*|flood\w*|"
        r"deep\s+water|bathtub\w*|waterfall\w*|canal\w*)\b",
        re.IGNORECASE,
    ),
}

SECRECY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsecrets?\b", re.IGNORECASE),
    re.compile(r"\b(?:do\s*n[o']?t|do\s+not|don't|never)\s+tell\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+telling\b", re.IGNORECASE),
    re.compile(r"\bbetween\s+(?:us|you\s+and\s+me)\b", re.IGNORECASE),
    re.compile(r"\bkeep\s+(?:it|this|that)\s+(?:quiet|hidden)\b", re.IGNORECASE),
    re.compile(r"\bhide\s+(?:it|this|that)\s+from\b", re.IGNORECASE),
)

DEPENDENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\byou\s+(?:only\s+)?need\s+me\b", re.IGNORECASE),
    re.compile(r"\bonly\s+i\s+(?:can|understand|care)\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m|\s+am)\s+your\s+(?:best\s+|only\s+)?friend\b", re.IGNORECASE),
    re.compile(r"\b(?:rely|depend|count)\s+on\s+me\b", re.IGNORECASE),
    re.compile(r"\bdo\s*n[o']?t\s+need\s+(?:anyone|anybody|other\s+people)\b", re.IGNORECASE),
    re.compile(r"\bcome\s+back\s+to\s+me\b", re.IGNORECASE),
    re.compile(r"\bi\s+will\s+always\s+be\s+(?:here\s+)?for\s+you\b", re.IGNORECASE),
    re.compile(r"\bno\s+one\s+(?:else\s+)?understands\s+you\b", re.IGNORECASE),
)


def activity_fields(activity: Activity) -> list[str]:
    """Every learner and facilitator text field of an Activity."""
    return [
        activity.instruction,
        activity.facilitator_note,
        activity.expected_answer,
        activity.rubric,
        *activity.hints,
        *activity.alternatives,
    ]


def scan_text(text: str) -> list[str]:
    """Return the safety violations found in ``text`` (R-08.1, R-08.5)."""
    found: list[str] = []
    for category, pattern in HAZARD_PATTERNS.items():
        if pattern.search(text):
            found.append(f"hazard: {category}")
    if any(p.search(text) for p in SECRECY_PATTERNS):
        found.append("secrecy: encourages keeping secrets from an adult")
    if any(p.search(text) for p in DEPENDENCE_PATTERNS):
        found.append("emotional dependence on the System")
    return found


def check_activity_safety(activity: Activity) -> GateResult:
    """Safety gate for one Activity across all of its text fields (R-08.1, R-08.5)."""
    reasons: list[str] = []
    for text in activity_fields(activity):
        for violation in scan_text(text):
            reason = f"activity {activity.id} {violation}"
            if reason not in reasons:
                reasons.append(reason)
    return GateResult(passed=not reasons, reasons=reasons)


def check_lesson_safety(lesson: Lesson) -> GateResult:
    """Safety gate for a Lesson; one unsafe Activity rejects the whole Lesson (R-08.2)."""
    reasons: list[str] = []
    for text in (lesson.title, lesson.objective, lesson.setup):
        for violation in scan_text(text):
            reason = f"lesson {violation}"
            if reason not in reasons:
                reasons.append(reason)
    for activity in lesson.activities:
        reasons.extend(check_activity_safety(activity).reasons)
    return GateResult(passed=not reasons, reasons=reasons)
