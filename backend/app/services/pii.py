"""PII detection and redaction (R-08.6, R-08.7; NFR-08, NFR-10).

Detects names, phone numbers, email addresses, street addresses, school names and birth
dates in Facilitator-supplied text. Detected PII is replaced with a typed placeholder
before any model call and a warning is returned for the Facilitator (R-08.6).

When redaction cannot be completed (obfuscated PII that cannot be located reliably, or PII
that is still detectable after redaction), ``PiiNotRedactableError`` is raised *before* any
model call is made. The guard is a pure function of its inputs: it never touches Session
data, so the Session's other data stays unchanged (R-08.7).

Detection is heuristic and deliberately biased toward privacy: a false positive costs a
placeholder in a prompt, a false negative leaks a child's identity to a model.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Generic, TypeVar

T = TypeVar("T")


class PiiType(StrEnum):
    """The PII categories named by R-08.6."""

    NAME = "name"
    PHONE = "phone"
    EMAIL = "email"
    ADDRESS = "address"
    SCHOOL = "school"
    BIRTH_DATE = "birth_date"


@dataclass(frozen=True)
class PiiMatch:
    """A detected PII span ``text[start:end]`` of the given type."""

    type: PiiType
    start: int
    end: int


@dataclass(frozen=True)
class RedactionResult:
    """Redacted text plus the PII types found; ``warning`` is set iff PII was redacted."""

    text: str
    types: tuple[PiiType, ...]
    warning: str | None

    @property
    def redacted(self) -> bool:
        """Whether any PII was redacted."""
        return bool(self.types)


@dataclass(frozen=True)
class GuardedResult(Generic[T]):  # noqa: UP046 - project targets Python 3.11
    """Result of a guarded model call: the model's result and the Facilitator warning."""

    result: T
    warning: str | None


NOT_REDACTABLE_MESSAGE: Final = (
    "Some personal information could not be removed automatically. Please remove any names, "
    "phone numbers, email addresses, street addresses, school names or birth dates and try again."
)


class PiiNotRedactableError(Exception):
    """Raised when PII cannot be redacted; no model call may be made (R-08.7)."""

    code = "pii_not_redactable"

    def __init__(self, message: str = NOT_REDACTABLE_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


# --- Patterns --------------------------------------------------------------------------------

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_TITLE_WORD = r"[A-Z][a-z]+(?:['-][A-Z]?[a-z]+)?"
_NAME_SEQ = rf"{_TITLE_WORD}(?:\s+{_TITLE_WORD}){{0,2}}"
_STREET_SUFFIX = (
    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|"
    r"Place|Pl|Terrace|Circle)"
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

_DATE_PATTERNS: Final = (
    re.compile(r"\b\d{4}[/.-]\d{1,2}[/.-]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\b"),
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(
        rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\.?,?\s+\d{{4}}\b", re.IGNORECASE
    ),
    # Cue words allow a date without a year: "birthday is March 3", "born on 3 March".
    re.compile(
        r"(?i:\b(?:birthday|bday|birth\s*date|date\s+of\s+birth|born)\b"
        rf"(?:\s+(?:is|on|was|:))*\s*)(?i:({_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?"
        rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b\.?))",
    ),
)

_ADDRESS = re.compile(
    rf"\b\d{{1,6}}\s+(?:(?:{_TITLE_WORD}|\d+(?:st|nd|rd|th))\s+){{1,4}}{_STREET_SUFFIX}\b\.?",
    re.IGNORECASE,
)
# Re-check that the words between number and suffix are capitalized (case-insensitive flag
# above is only for the street suffix), so "2 small stones in the lane" is not an address.
_ADDRESS_WORDS = re.compile(rf"^\d+\s+(?:(?:{_TITLE_WORD}|\d+(?:st|nd|rd|th))\s+)+")

_PHONE = re.compile(r"(?<![\w])\+?\(?\d[\d\s().-]{5,}\d(?!\w)")

_SCHOOL_PATTERNS: Final = (
    re.compile(
        rf"\b(?:{_TITLE_WORD}\s+){{1,4}}(?:School|Academy|Elementary|Kindergarten|Preschool|"
        r"Montessori|College|University|Institute)\b"
        r"(?:\s+(?:School|Elementary))?"
    ),
    re.compile(rf"(?i:\b(?:attends|attending|studies\s+at|student\s+at)\s+)({_NAME_SEQ})"),
    re.compile(rf"(?i:\bschool\s+(?:is\s+)?(?:called|named)\s+)({_NAME_SEQ})"),
)

_NAME_PATTERNS: Final = (
    re.compile(rf"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?\s+({_NAME_SEQ})"),
    re.compile(rf"(?i:\b(?:my|his|her|their|our)\s+name\s+is\s+)({_NAME_SEQ})"),
    re.compile(rf"(?i:\bname\s+is\s+)({_NAME_SEQ})"),
    re.compile(rf"(?i:\b(?:i\s+am|i'm|this\s+is|called|named)\s+)({_NAME_SEQ})"),
    re.compile(
        r"(?i:\b(?:my|his|her|their|our)\s+"
        r"(?:child|son|daughter|kid|student|pupil|learner|grandson|granddaughter|"
        r"nephew|niece)(?:'s)?\s+(?:name\s+)?(?:is\s+|named\s+|called\s+)?)"
        rf"({_NAME_SEQ})"
    ),
)

# PII that is present but cannot be located precisely enough to redact (R-08.7).
_UNREDACTABLE: Final = (
    # "jo at example dot com"
    re.compile(
        r"\b[\w.-]+\s*[\[(]?\s*at\s*[\])]?\s*[\w-]+\s*[\[(]?\s*dot\s*[\])]?\s*[a-z]{2,}\b",
        re.IGNORECASE,
    ),
    # Seven or more spelled-out digits: "five five five one two three four"
    re.compile(
        r"(?:\b(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)\b[\s,.-]*){7,}",
        re.IGNORECASE,
    ),
)


def _is_phone(candidate: str) -> bool:
    digits = sum(ch.isdigit() for ch in candidate)
    return 7 <= digits <= 15


def _is_address(candidate: str) -> bool:
    return _ADDRESS_WORDS.match(candidate) is not None


def _spans(
    pii_type: PiiType,
    patterns: Sequence[re.Pattern[str]],
    text: str,
    validator: Callable[[str], bool] | None = None,
) -> list[PiiMatch]:
    found: list[PiiMatch] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            group = 1 if pattern.groups else 0
            if m.start(group) < 0 or m.start(group) == m.end(group):
                continue
            if validator is not None and not validator(m.group(0)):
                continue
            found.append(PiiMatch(pii_type, m.start(group), m.end(group)))
    return found


def detect_pii(text: str) -> list[PiiMatch]:
    """Return non-overlapping PII spans in ``text`` sorted by position (R-08.6).

    When spans from different categories overlap, the earlier category in the order
    email, birth date, address, phone, school, name wins.
    """
    candidates: list[PiiMatch] = [
        *_spans(PiiType.EMAIL, [_EMAIL], text),
        *_spans(PiiType.BIRTH_DATE, _DATE_PATTERNS, text),
        *_spans(PiiType.ADDRESS, [_ADDRESS], text, _is_address),
        *_spans(PiiType.PHONE, [_PHONE], text, _is_phone),
        *_spans(PiiType.SCHOOL, _SCHOOL_PATTERNS, text),
        *_spans(PiiType.NAME, _NAME_PATTERNS, text),
    ]
    accepted: list[PiiMatch] = []
    for cand in candidates:
        if all(cand.end <= a.start or cand.start >= a.end for a in accepted):
            accepted.append(cand)
    return sorted(accepted, key=lambda m: m.start)


def _has_unredactable(text: str) -> bool:
    return any(p.search(text) for p in _UNREDACTABLE)


def _warning(types: Sequence[PiiType]) -> str:
    labels = ", ".join(t.value.replace("_", " ") for t in types)
    return (
        f"Personal information was detected and redacted before processing ({labels}). "
        "Please avoid entering personal information."
    )


def redact_pii(text: str) -> RedactionResult:
    """Redact PII in ``text``; raise ``PiiNotRedactableError`` if that cannot be completed.

    Each span is replaced by ``[REDACTED_<TYPE>]``. After redaction the text is checked
    again; any remaining detectable PII means redaction did not complete (R-08.7).
    """
    if _has_unredactable(text):
        raise PiiNotRedactableError
    matches = detect_pii(text)
    if not matches:
        return RedactionResult(text=text, types=(), warning=None)

    out = text
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        out = f"{out[: m.start]}[REDACTED_{m.type.name}]{out[m.end :]}"

    if detect_pii(out) or _has_unredactable(out):
        raise PiiNotRedactableError

    types = tuple(dict.fromkeys(m.type for m in sorted(matches, key=lambda x: x.start)))
    return RedactionResult(text=out, types=types, warning=_warning(types))


def redact_all(texts: Sequence[str]) -> tuple[list[str], str | None]:
    """Redact every text atomically; return redacted texts and one combined warning.

    If any text cannot be redacted, ``PiiNotRedactableError`` is raised and nothing is
    returned, so the caller cannot send a partially redacted input set (R-08.7).
    """
    results = [redact_pii(t) for t in texts]
    types = tuple(dict.fromkeys(t for r in results for t in r.types))
    return [r.text for r in results], (_warning(types) if types else None)


def guarded_model_call(texts: Sequence[str], call: Callable[[list[str]], T]) -> GuardedResult[T]:
    """Redact ``texts`` and only then invoke ``call`` with the redacted texts (R-08.6).

    If redaction cannot complete, ``PiiNotRedactableError`` propagates and ``call`` is
    never invoked (R-08.7). No Session data is read or written here.
    """
    redacted, warning = redact_all(texts)
    return GuardedResult(result=call(redacted), warning=warning)
