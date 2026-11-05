"""Object normalizer: trim, collapse whitespace, dedupe, enforce bounds (R-02.1, R-02.2).

The Normalizer turns the Facilitator's raw object strings into an ``ObjectInventory``
of ``ObjectItem`` entries. For each retained item the original entered text is kept
unchanged while the normalized key (trimmed, internal whitespace collapsed, case
folded) is used for case-insensitive deduplication. Bounds are 1 to 20 unique objects
and each name at most 50 characters (R-02.1). When a bound is exceeded the error names
which limit was violated so the API/Web_UI can report it (R-02.2).
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.models import ObjectInventory, ObjectItem, _norm

MIN_OBJECTS = 1
MAX_OBJECTS = 20
MAX_NAME_LENGTH = 50


class LimitName(StrEnum):
    """Names the object limit that a submission violated (R-02.2)."""

    TOO_FEW_OBJECTS = "too_few_objects"
    TOO_MANY_OBJECTS = "too_many_objects"
    NAME_TOO_LONG = "name_too_long"


class NormalizationError(ValueError):
    """Raised when object input violates a bound; carries the violated limit (R-02.2)."""

    def __init__(self, limit: LimitName, message: str) -> None:
        super().__init__(message)
        self.limit = limit


def normalize_objects(objects: list[str]) -> ObjectInventory:
    """Normalize and dedupe ``objects`` into a bounded ``ObjectInventory`` (R-02.1, R-02.2).

    Leading/trailing whitespace is trimmed and internal whitespace collapsed for the
    normalized comparison key. Items whose normalized keys match are deduplicated,
    keeping the first occurrence's original text unchanged. An empty normalized key
    (whitespace-only input) contributes no object.

    Raises ``NormalizationError`` naming the violated limit when a name exceeds 50
    characters, when no valid objects remain, or when more than 20 unique objects are
    supplied.
    """
    items: list[ObjectItem] = []
    seen: set[str] = set()

    for original in objects:
        trimmed = original.strip()
        normalized = _norm(original)
        if not normalized:
            continue
        if len(trimmed) > MAX_NAME_LENGTH or len(normalized) > MAX_NAME_LENGTH:
            raise NormalizationError(
                LimitName.NAME_TOO_LONG,
                f"object name exceeds {MAX_NAME_LENGTH} characters: {original!r}",
            )
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(ObjectItem(original=trimmed, normalized=normalized))

    if len(items) < MIN_OBJECTS:
        raise NormalizationError(
            LimitName.TOO_FEW_OBJECTS,
            f"at least {MIN_OBJECTS} unique object is required",
        )
    if len(items) > MAX_OBJECTS:
        raise NormalizationError(
            LimitName.TOO_MANY_OBJECTS,
            f"at most {MAX_OBJECTS} unique objects are allowed",
        )

    return ObjectInventory(items=items)
