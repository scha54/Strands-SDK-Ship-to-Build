"""Idempotency service for session mutations (R-05.3, R-11.2, R-11.7; NFR-05).

Every session mutation that carries an ``Idempotency-Key`` runs through this service so a
retried request applies its state change exactly once. The design's contract is:

* Compute a ``payload_hash`` over the canonicalized request payload.
* Look up the key among the session's stored :class:`~app.domain.models.IdempotencyRecord`
  entries, keeping only records created within the 24 h window measured against the
  injected clock. A record older than the window is treated as if it never existed, so a
  reused key outside the window is a fresh mutation (R-11.2).
* Same key and same ``payload_hash`` within the window: return the stored result reference
  with no re-execution (R-05.3, R-11.2).
* Same key but a different ``payload_hash`` within the window: raise
  :class:`IdempotencyKeyConflict` (code ``idempotency_key_conflict``, HTTP 409) and change
  nothing (R-11.7).
* A new key (or one whose record has aged out): the caller executes the mutation and then
  persists the new :class:`IdempotencyRecord` in the *same* conditional write
  (:meth:`~app.adapters.session_store.SessionStore.put_if_version`) as the state change, so
  the record and the state transition commit together or not at all. :func:`append_record`
  returns the record list to store; the caller passes it on the ``SessionRecord`` it writes.

Hashing is deterministic and payload-shape agnostic: payloads are serialized with sorted
keys and no insignificant whitespace, so logically equal payloads hash equally regardless
of field order. The clock is injected so expiry of the window is deterministic in tests,
consistent with the Session_Store's expiry handling.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from app.adapters.session_store import SessionStoreError
from app.domain.models import IdempotencyRecord

# Default idempotency window; the config value (IC_IDEMPOTENCY_WINDOW_HOURS) is the source of
# truth and callers may override via ``window``. Mirrors the 24 h retention in R-11.2.
DEFAULT_WINDOW = timedelta(hours=24)


class IdempotencyKeyConflict(SessionStoreError):
    """Reused key with a different payload within the window (HTTP 409, code per R-11.7)."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"idempotency key reused with a different payload: {key!r}",
            code="idempotency_key_conflict",
        )
        self.key = key


def compute_payload_hash(payload: Any) -> str:
    """Return a stable SHA-256 hex digest for ``payload`` (R-11.7).

    The payload is serialized as JSON with sorted keys and compact separators so that two
    logically equal payloads produce the same hash regardless of key order or incidental
    whitespace. ``None`` is a valid payload (hashes a JSON ``null``), which covers mutations
    with an empty body.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _within_window(record: IdempotencyRecord, key: str, now: datetime, window: timedelta) -> bool:
    """Return whether ``record`` matches ``key`` and is still inside the retention window.

    A record created at or before ``now - window`` has aged out and is treated as absent
    (R-11.2), consistent with the store's clock-driven expiry.
    """
    if record.key != key:
        return False
    return record.created_at > now - window


def lookup(
    records: Sequence[IdempotencyRecord],
    key: str,
    payload_hash: str,
    now: datetime,
    *,
    window: timedelta = DEFAULT_WINDOW,
) -> IdempotencyRecord | None:
    """Resolve an idempotency ``key`` against the session's stored records.

    Returns the matching record when the key and ``payload_hash`` agree within the window
    (the caller then replays its stored result with no re-execution). Returns ``None`` when
    the key is new or its record has aged out of the window (the caller executes the
    mutation). Raises :class:`IdempotencyKeyConflict` when the key is present within the
    window but the payload differs (R-11.7).
    """
    for record in records:
        if not _within_window(record, key, now, window):
            continue
        if record.payload_hash == payload_hash:
            return record
        raise IdempotencyKeyConflict(key)
    return None


def append_record(
    records: Sequence[IdempotencyRecord],
    key: str,
    route: str,
    payload_hash: str,
    now: datetime,
    *,
    result_ref: str | None = None,
    window: timedelta = DEFAULT_WINDOW,
) -> list[IdempotencyRecord]:
    """Return the record list to persist for a newly executed mutation (R-05.3).

    Drops any record for ``key`` that has aged out of the window, then appends a fresh
    record ``{key, route, payload_hash, result_ref, created_at=now}``. The caller sets this
    list on the ``SessionRecord`` it writes via ``put_if_version`` so the idempotency record
    and the state change commit in the same conditional write — the mutation is therefore
    applied exactly once under retries.
    """
    retained = [r for r in records if not (r.key == key and r.created_at <= now - window)]
    retained.append(
        IdempotencyRecord(
            key=key,
            route=route,
            payload_hash=payload_hash,
            result_ref=result_ref,
            created_at=now,
        )
    )
    return retained
