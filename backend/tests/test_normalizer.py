"""Unit tests for the object normalizer (R-02.1, R-02.2; NFR-02)."""

import pytest
from app.services.normalizer import (
    LimitName,
    NormalizationError,
    normalize_objects,
)


def test_trims_leading_and_trailing_whitespace() -> None:
    """R-02.1: leading/trailing whitespace is trimmed, original text kept trimmed."""
    inv = normalize_objects(["  stone  "])
    assert len(inv.items) == 1
    assert inv.items[0].original == "stone"
    assert inv.items[0].normalized == "stone"


def test_collapses_internal_whitespace_in_normalized_key() -> None:
    """R-02.1: internal whitespace is collapsed for the normalized comparison key."""
    inv = normalize_objects(["red  \t  cup"])
    assert len(inv.items) == 1
    assert inv.items[0].normalized == "red cup"


def test_case_insensitive_duplicates_are_deduped_keeping_first_original() -> None:
    """R-02.1: case-insensitive duplicates collapse, first original text is retained."""
    inv = normalize_objects(["Stone", "stone", " STONE "])
    assert len(inv.items) == 1
    assert inv.items[0].original == "Stone"
    assert inv.items[0].normalized == "stone"


def test_whitespace_variant_duplicates_are_deduped() -> None:
    """R-02.1: items equal after trim and whitespace collapse are deduped."""
    inv = normalize_objects(["red cup", "red   cup", "  red cup "])
    assert len(inv.items) == 1
    assert inv.items[0].original == "red cup"


def test_distinct_objects_are_all_kept() -> None:
    """R-02.1: distinct normalized keys each produce a retained item."""
    inv = normalize_objects(["stone", "leaf", "cup"])
    assert [i.normalized for i in inv.items] == ["stone", "leaf", "cup"]


def test_zero_objects_rejected_names_too_few_limit() -> None:
    """R-02.2: empty/whitespace-only input is rejected naming the too-few limit."""
    with pytest.raises(NormalizationError) as exc:
        normalize_objects(["   ", "\t"])
    assert exc.value.limit is LimitName.TOO_FEW_OBJECTS


def test_empty_list_rejected_names_too_few_limit() -> None:
    """R-02.2: an empty object list is rejected naming the too-few limit."""
    with pytest.raises(NormalizationError) as exc:
        normalize_objects([])
    assert exc.value.limit is LimitName.TOO_FEW_OBJECTS


def test_twenty_one_unique_objects_rejected_names_too_many_limit() -> None:
    """R-02.2: 21 unique objects are rejected naming the too-many limit."""
    objects = [f"object{i}" for i in range(21)]
    with pytest.raises(NormalizationError) as exc:
        normalize_objects(objects)
    assert exc.value.limit is LimitName.TOO_MANY_OBJECTS


def test_exactly_twenty_unique_objects_allowed() -> None:
    """R-02.1: the upper bound of 20 unique objects is accepted."""
    objects = [f"object{i}" for i in range(20)]
    inv = normalize_objects(objects)
    assert len(inv.items) == 20


def test_twenty_one_entries_that_dedupe_to_twenty_are_allowed() -> None:
    """R-02.1: dedupe applies before the count bound is enforced."""
    objects = [f"object{i}" for i in range(20)] + ["OBJECT0"]
    inv = normalize_objects(objects)
    assert len(inv.items) == 20


def test_fifty_one_char_name_rejected_names_length_limit() -> None:
    """R-02.2: a name longer than 50 characters is rejected naming the length limit."""
    with pytest.raises(NormalizationError) as exc:
        normalize_objects(["x" * 51])
    assert exc.value.limit is LimitName.NAME_TOO_LONG


def test_fifty_char_name_allowed() -> None:
    """R-02.1: a name of exactly 50 characters is accepted."""
    inv = normalize_objects(["x" * 50])
    assert len(inv.items) == 1
    assert len(inv.items[0].normalized) == 50
