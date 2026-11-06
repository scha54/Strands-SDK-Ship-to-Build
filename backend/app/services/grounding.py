"""Grounding gate and ambiguity/hazard handling for Objects (R-02.3 to R-02.6, R-08.1; NFR-10).

Deterministic, model-free checks. The grounding gate passes only when every object an
Activity (or the Lesson) references is in the Object_Inventory, is not excluded as
hazardous, and no purchased supplies or paid services are required (R-02.5, R-02.6).
Ambiguous Objects receive a visible one-sentence assumption of at most 100 characters
(R-02.3). Hazardous Objects are excluded with a safe alternative and a Facilitator
notice (R-02.4, R-08.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.models import (
    Activity,
    GateResult,
    Lesson,
    ObjectInventory,
    ObjectItem,
    _norm,
)

MAX_ASSUMPTION_LENGTH = 100

# Vague names that cannot be turned into a concrete Activity without an assumption.
AMBIGUOUS_TERMS: frozenset[str] = frozenset(
    {"stuff", "things", "thing", "items", "item", "misc", "miscellaneous", "junk", "toys"}
)

# Hazardous Object term -> (reason, safe alternative use).
HAZARD_OBJECTS: dict[str, tuple[str, str]] = {
    "knife": ("sharp object", "Use a blunt plastic spoon for scooping and sorting."),
    "knives": ("sharp object", "Use blunt plastic spoons for scooping and sorting."),
    "scissors": ("sharp object", "Tear paper by hand instead of cutting."),
    "blade": ("sharp object", "Use a paper strip for measuring edges."),
    "matches": ("fire", "Count or sort the matchboxes' empty paper tubes instead."),
    "lighter": ("fire", "Use a flashlight-free activity such as counting buttons."),
    "candle": ("fire", "Use a plain paper tube to practice measuring height."),
    "stove": ("fire", "Use play food or pebbles to practice counting."),
    "bleach": ("hazardous chemical", "Use an empty, rinsed plastic bottle as a counter."),
    "detergent": ("hazardous chemical", "Use an empty, rinsed plastic bottle as a counter."),
    "medicine": ("ingestion hazard", "Use dried beans in a closed jar for counting."),
    "pills": ("ingestion hazard", "Use large buttons for counting."),
    "battery": ("electricity", "Use a round stone or button for counting."),
    "batteries": ("electricity", "Use round stones or buttons for counting."),
    "socket": ("electricity", "Use a paper plate to practice sorting."),
    "wire": ("electricity", "Use a piece of string for measuring length."),
    "ladder": ("heights", "Measure low objects on the floor instead."),
    "rope": ("heights", "Use a short piece of string for measuring on the floor."),
}

# Phrases showing an Activity needs purchased supplies or paid services (R-02.5).
_PURCHASE_PATTERN = re.compile(
    r"\b(buy|buying|bought|purchase[sd]?|purchasing|store[- ]bought|paid|pay for|"
    r"subscription|subscribe|download an app|order online|shopping)\b",
    re.IGNORECASE,
)


@dataclass
class HazardOutcome:
    """Result of hazard handling: the updated inventory and Facilitator notices."""

    inventory: ObjectInventory
    notices: list[str] = field(default_factory=list)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _is_one_sentence(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    body = stripped.rstrip(".!?")
    return not re.search(r"[.!?]", body)


def set_assumption(item: ObjectItem, assumption: str) -> ObjectItem:
    """Return ``item`` carrying a visible one-sentence assumption of at most 100 chars (R-02.3)."""
    text = assumption.strip()
    if len(text) > MAX_ASSUMPTION_LENGTH:
        raise ValueError(f"assumption exceeds {MAX_ASSUMPTION_LENGTH} characters")
    if not _is_one_sentence(text):
        raise ValueError("assumption must be exactly one sentence")
    return item.model_copy(update={"assumption": text})


def is_ambiguous(item: ObjectItem) -> bool:
    """An Object is ambiguous when its name is a vague generic term (R-02.3)."""
    return item.normalized in AMBIGUOUS_TERMS


def label_ambiguous(inventory: ObjectInventory) -> ObjectInventory:
    """Attach a short visible safe assumption to each ambiguous Object (R-02.3)."""
    items: list[ObjectItem] = []
    for item in inventory.items:
        if is_ambiguous(item) and item.assumption is None:
            text = f"Assuming '{item.normalized}' means small, safe, everyday household items."
            if len(text) > MAX_ASSUMPTION_LENGTH:
                text = "Assuming this means small, safe, everyday household items."
            item = set_assumption(item, text)
        items.append(item)
    return ObjectInventory(items=items)


def handle_hazards(inventory: ObjectInventory) -> HazardOutcome:
    """Exclude hazardous Objects, add a safe alternative and notice (R-02.4, R-08.1)."""
    items: list[ObjectItem] = []
    notices: list[str] = []
    for item in inventory.items:
        hit = next((t for t in sorted(_words(item.normalized)) if t in HAZARD_OBJECTS), None)
        if hit is not None and item.excluded_reason is None:
            reason, alternative = HAZARD_OBJECTS[hit]
            item = item.model_copy(
                update={"excluded_reason": reason, "safe_alternative": alternative}
            )
            notices.append(
                f"'{item.original}' was excluded from all Activities ({reason}). "
                f"Safe alternative: {alternative}"
            )
        elif item.excluded_reason is not None:
            notices.append(f"'{item.original}' was excluded from all Activities.")
        items.append(item)
    return HazardOutcome(inventory=ObjectInventory(items=items), notices=notices)


def _excluded_names(inventory: ObjectInventory) -> set[str]:
    return {i.normalized for i in inventory.items if i.excluded_reason is not None}


def _activity_text(activity: Activity) -> str:
    return f"{activity.instruction} {activity.facilitator_note}"


def check_activity(activity: Activity, inventory: ObjectInventory) -> GateResult:
    """Grounding gate for one Activity (R-02.5, R-02.6)."""
    reasons: list[str] = []
    allowed = inventory.normalized_names()
    excluded = _excluded_names(inventory)
    for obj in activity.required_objects:
        key = _norm(obj)
        if key in excluded:
            reasons.append(f"activity {activity.id} uses excluded hazardous object: {obj}")
        elif key not in allowed:
            reasons.append(f"activity {activity.id} uses item not in inventory: {obj}")
    text_words = _words(_activity_text(activity))
    for name in sorted(excluded):
        if name in _norm(_activity_text(activity)) or _words(name) <= text_words:
            reasons.append(f"activity {activity.id} mentions excluded hazardous object: {name}")
    if _PURCHASE_PATTERN.search(_activity_text(activity)):
        reasons.append(f"activity {activity.id} requires purchased supplies or paid services")
    return GateResult(passed=not reasons, reasons=reasons)


def check_lesson(lesson: Lesson, inventory: ObjectInventory) -> GateResult:
    """Grounding gate for a Lesson: its object list and every Activity (R-02.5, R-02.6)."""
    reasons: list[str] = []
    allowed = inventory.normalized_names()
    excluded = _excluded_names(inventory)
    for obj in lesson.objects:
        key = _norm(obj)
        if key in excluded:
            reasons.append(f"lesson uses excluded hazardous object: {obj}")
        elif key not in allowed:
            reasons.append(f"lesson uses item not in inventory: {obj}")
    for activity in lesson.activities:
        reasons.extend(check_activity(activity, inventory).reasons)
    return GateResult(passed=not reasons, reasons=reasons)
