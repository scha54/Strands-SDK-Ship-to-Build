"""Unit tests for the grounding gate and Object ambiguity/hazard handling.

Covers R-02.3, R-02.4, R-02.5, R-02.6, R-08.1; NFR-10.
"""

import pytest
from app.domain.models import Activity, Lesson, ObjectInventory, Question
from app.services.grounding import (
    check_activity,
    check_lesson,
    handle_hazards,
    label_ambiguous,
    set_assumption,
)
from app.services.normalizer import normalize_objects


def _activity(aid: str, objects: list[str], instruction: str = "Count the items.") -> Activity:
    return Activity(
        id=aid,
        instruction=instruction,
        facilitator_note="Guide gently.",
        required_objects=objects,
        answer_kind="integer",
        expected_answer="3",
        rubric="Counts correctly.",
        hints=["Count slowly."],
        difficulty=1,
    )


def _lesson(activities: list[Activity], objects: list[str]) -> Lesson:
    q = Question(id="q", topic="count", prompt="How many?", scale_max=5)
    return Lesson(
        source="generated",
        title="T",
        objective="Count",
        objects=objects,
        setup="Set up.",
        activities=activities,
        baseline_question=q,
        end_question=q,
        estimated_minutes=5,
    )


def test_in_inventory_activity_passes() -> None:
    """R-02.5: an Activity using only inventory Objects passes the gate."""
    inv = normalize_objects(["Stone", "cup"])
    assert check_activity(_activity("a1", ["stone", "CUP"]), inv).passed


def test_off_inventory_item_fails_gate() -> None:
    """R-02.6: an item not in the inventory fails the gate with a reason."""
    inv = normalize_objects(["stone"])
    result = check_activity(_activity("a1", ["stone", "tablet"]), inv)
    assert not result.passed
    assert any("tablet" in r for r in result.reasons)


def test_purchased_supplies_fail_gate() -> None:
    """R-02.5: an Activity requiring purchases fails even with inventory objects."""
    inv = normalize_objects(["stone"])
    result = check_activity(_activity("a1", ["stone"], "Buy more stones, then count."), inv)
    assert not result.passed


def test_lesson_with_off_inventory_object_fails() -> None:
    """R-02.6, NFR-10: Lesson object list is checked as well as Activities."""
    inv = normalize_objects(["stone"])
    acts = [_activity(f"a{i}", ["stone"]) for i in range(3)]
    assert check_lesson(_lesson(acts, ["stone"]), inv).passed
    assert not check_lesson(_lesson(acts, ["stone", "robot"]), inv).passed


def test_ambiguous_object_carries_short_assumption() -> None:
    """R-02.3: an ambiguous Object gets a one-sentence assumption of at most 100 chars."""
    inv = label_ambiguous(normalize_objects(["stuff", "stone"]))
    stuff, stone = inv.items
    assert stuff.assumption is not None
    assert len(stuff.assumption) <= 100
    assert stone.assumption is None


def test_assumption_rejects_long_or_multi_sentence() -> None:
    """R-02.3: assumptions over 100 chars or with several sentences are refused."""
    item = normalize_objects(["stuff"]).items[0]
    with pytest.raises(ValueError):
        set_assumption(item, "x" * 101)
    with pytest.raises(ValueError):
        set_assumption(item, "One. Two.")
    assert set_assumption(item, "Assuming small items.").assumption == "Assuming small items."


def test_hazardous_object_excluded_with_alternative_and_notice() -> None:
    """R-02.4, R-08.1: hazardous Object is excluded, has an alternative, and yields a notice."""
    outcome = handle_hazards(normalize_objects(["Scissors", "stone"]))
    scissors, stone = outcome.inventory.items
    assert scissors.excluded_reason is not None
    assert scissors.safe_alternative
    assert stone.excluded_reason is None
    assert len(outcome.notices) == 1
    assert "Scissors" in outcome.notices[0]


def test_excluded_hazardous_object_appears_in_no_activity() -> None:
    """R-02.4: an Activity using an excluded Object fails the gate."""
    inv: ObjectInventory = handle_hazards(normalize_objects(["scissors", "stone"])).inventory
    by_list = check_activity(_activity("a1", ["scissors"]), inv)
    by_text = check_activity(_activity("a2", ["stone"], "Cut paper with scissors."), inv)
    assert not by_list.passed
    assert not by_text.passed
    assert check_activity(_activity("a3", ["stone"]), inv).passed
