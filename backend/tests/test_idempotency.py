"""Unit tests for the idempotency service (R-05.3, R-11.2, R-11.7; NFR-05).

These tests show, against the in-memory Session_Store, that:

* Repeat calls with the same key and payload apply the mutation exactly once and return the
  stored result (R-05.3, R-11.2).
* A conflicting payload (same key, different hash) within the window returns a 409
  ``idempotency_key_conflict`` and leaves stored results unchanged (R-11.7).
* A key whose record is older than 24 h is treated as new (R-11.2).

The service's lookup/append helpers are exercised directly and also end-to-end through the
store's conditional write (``put_if_version``) to confirm the record is persisted in the
same write as the state change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.adapters.session_store import InMemorySessionStore, new_session_id
from app.domain.models import (
    AgeBand,
    IdempotencyRecord,
    SessionRecord,
    Subject,
)
from app.services.idempotency import (
    DEFAULT_WINDOW,
    IdempotencyKeyConflict,
    append_record,
    compute_payload_hash,
    lookup,
)

BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
ROUTE = "/sessions/{id}/answers"


def make_record(created: datetime = BASE_TIME) -> SessionRecord:
    """A valid session record with no idempotency entries and a known state."""
    return SessionRecord(
        session_id=new_session_id(),
        token_hash="hash-of-capability-token",  # noqa: S106 - a hash, not a secret
        state="active",
        age_band=AgeBand.B6_8,
        subject=Subject.ARITHMETIC,
        current_index=0,
        created_at=created,
        updated_at=created,
        expires_at=created,  # refreshed to updated_at + TTL by the store on persist
        version=0,
    )


# --- payload hashing ------------------------------------------------------------------------


def test_payload_hash_is_order_independent() -> None:
    """Logically equal payloads hash equally regardless of key order. Validates: R-11.7."""
    a = compute_payload_hash({"answer": "4", "activity_id": "a1"})
    b = compute_payload_hash({"activity_id": "a1", "answer": "4"})
    assert a == b


def test_payload_hash_differs_for_different_payloads() -> None:
    """Different payloads hash differently. Validates: R-11.7."""
    assert compute_payload_hash({"answer": "4"}) != compute_payload_hash({"answer": "5"})


# --- scenario 1: repeat calls apply the mutation once ---------------------------------------


def test_repeat_call_same_key_and_payload_applies_mutation_once() -> None:
    """Same key + payload within the window re-applies nothing and replays the result.

    Validates: R-05.3, R-11.2.
    """
    store = InMemorySessionStore()
    record = make_record()
    store.create(record)

    key = "idem-1"
    payload = {"activity_id": "a1", "answer": "4"}
    payload_hash = compute_payload_hash(payload)

    # First call: no prior record, so the caller executes the mutation and persists the
    # idempotency record in the SAME conditional write as the state change.
    current = store.get(record.session_id, BASE_TIME)
    assert lookup(current.idempotency, key, payload_hash, BASE_TIME) is None
    new_idempotency = append_record(
        current.idempotency, key, ROUTE, payload_hash, BASE_TIME, result_ref="answer#a1"
    )
    mutated = current.model_copy(
        update={"current_index": 1, "idempotency": new_idempotency}
    )
    store.put_if_version(mutated, expected=current.version)

    after_first = store.get(record.session_id, BASE_TIME)
    assert after_first.current_index == 1
    assert after_first.version == 1
    assert len(after_first.idempotency) == 1

    # Repeat calls: the stored record is found, so the mutation is NOT re-applied and the
    # original result reference is replayed. State is identical no matter how many repeats.
    for _ in range(5):
        current = store.get(record.session_id, BASE_TIME)
        hit = lookup(current.idempotency, key, payload_hash, BASE_TIME)
        assert hit is not None
        assert hit.result_ref == "answer#a1"
        # No write happens on a replay; confirm nothing changed.

    final = store.get(record.session_id, BASE_TIME)
    assert final.current_index == 1  # mutation applied exactly once
    assert final.version == 1  # no further writes
    assert len(final.idempotency) == 1


# --- scenario 2: conflicting payload returns 409 with results unchanged ---------------------


def test_conflicting_payload_raises_key_conflict_and_changes_nothing() -> None:
    """Same key, different payload within the window: 409 and no state change.

    Validates: R-11.7.
    """
    store = InMemorySessionStore()
    record = make_record()
    store.create(record)

    key = "idem-2"
    first_payload_hash = compute_payload_hash({"answer": "4"})
    conflicting_payload_hash = compute_payload_hash({"answer": "5"})

    current = store.get(record.session_id, BASE_TIME)
    new_idempotency = append_record(
        current.idempotency, key, ROUTE, first_payload_hash, BASE_TIME, result_ref="answer#a1"
    )
    mutated = current.model_copy(update={"current_index": 1, "idempotency": new_idempotency})
    store.put_if_version(mutated, expected=current.version)

    before = store.get(record.session_id, BASE_TIME)

    with pytest.raises(IdempotencyKeyConflict) as exc_info:
        lookup(before.idempotency, key, conflicting_payload_hash, BASE_TIME)

    assert exc_info.value.code == "idempotency_key_conflict"

    # Stored results are unchanged: no write occurred on the conflict path.
    after = store.get(record.session_id, BASE_TIME)
    assert after.current_index == 1
    assert after.version == 1
    assert len(after.idempotency) == 1
    assert after.idempotency[0].payload_hash == first_payload_hash


# --- scenario 3: a key older than 24 h is treated as new ------------------------------------


def test_key_older_than_window_is_treated_as_new() -> None:
    """A record created more than 24 h before now is ignored on lookup. Validates: R-11.2."""
    aged = IdempotencyRecord(
        key="idem-3",
        route=ROUTE,
        payload_hash=compute_payload_hash({"answer": "4"}),
        result_ref="answer#old",
        created_at=BASE_TIME,
    )
    now = BASE_TIME + DEFAULT_WINDOW + timedelta(seconds=1)

    # Even with a DIFFERENT payload, the aged-out record must not cause a conflict: it is
    # treated as absent, so lookup returns None (the caller executes a fresh mutation).
    assert lookup([aged], "idem-3", compute_payload_hash({"answer": "5"}), now) is None
    assert lookup([aged], "idem-3", aged.payload_hash, now) is None


def test_key_exactly_at_window_boundary_is_treated_as_new() -> None:
    """A record created exactly 24 h before now is outside the window. Validates: R-11.2."""
    aged = IdempotencyRecord(
        key="idem-boundary",
        route=ROUTE,
        payload_hash=compute_payload_hash({"answer": "4"}),
        created_at=BASE_TIME,
    )
    at_boundary = BASE_TIME + DEFAULT_WINDOW
    assert lookup([aged], "idem-boundary", aged.payload_hash, at_boundary) is None


def test_key_just_inside_window_is_a_hit() -> None:
    """A record created just under 24 h before now is still live. Validates: R-11.2."""
    live = IdempotencyRecord(
        key="idem-live",
        route=ROUTE,
        payload_hash=compute_payload_hash({"answer": "4"}),
        result_ref="answer#a1",
        created_at=BASE_TIME,
    )
    just_inside = BASE_TIME + DEFAULT_WINDOW - timedelta(seconds=1)
    hit = lookup([live], "idem-live", live.payload_hash, just_inside)
    assert hit is not None
    assert hit.result_ref == "answer#a1"


def test_append_record_drops_aged_entry_and_adds_fresh() -> None:
    """A new execution after the window replaces the aged record with a fresh one.

    Validates: R-05.3, R-11.2.
    """
    aged = IdempotencyRecord(
        key="idem-4",
        route=ROUTE,
        payload_hash=compute_payload_hash({"answer": "4"}),
        created_at=BASE_TIME,
    )
    now = BASE_TIME + DEFAULT_WINDOW + timedelta(hours=1)
    new_hash = compute_payload_hash({"answer": "5"})

    result = append_record([aged], "idem-4", ROUTE, new_hash, now, result_ref="answer#new")

    assert len(result) == 1  # the aged entry for the same key was dropped
    assert result[0].created_at == now
    assert result[0].payload_hash == new_hash
    assert result[0].result_ref == "answer#new"


def test_append_record_keeps_other_keys() -> None:
    """Appending a record for one key leaves records for other keys intact. Validates: R-11.2."""
    other = IdempotencyRecord(
        key="other",
        route=ROUTE,
        payload_hash=compute_payload_hash({"answer": "1"}),
        created_at=BASE_TIME,
    )
    result = append_record(
        [other], "new-key", ROUTE, compute_payload_hash({"answer": "2"}), BASE_TIME
    )
    keys = {r.key for r in result}
    assert keys == {"other", "new-key"}
