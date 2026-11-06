"""Session_Store: in-memory and DynamoDB backends (R-01.2, R-10.1, R-10.2, R-10.5-R-10.8; NFR-08).

The store persists a :class:`~app.domain.models.SessionRecord` keyed by an opaque
``session_id``. Only the attributes listed in the design's persisted-record table are
stored; ``SessionRecord`` forbids extra fields so a forbidden attribute (child name,
birthday, address, school, email, cross-session link, raw image) cannot be persisted
(R-10.1, R-10.2).

Both backends share this contract:

* ``create`` inserts a new record, failing if the ``session_id`` already exists.
* ``get(session_id, now)`` returns the record, raising :class:`NotFound` when it is
  absent and :class:`Expired` when ``expires_at`` is at or before ``now``. The expiry
  check uses the injected clock value ``now`` and happens before any TTL-driven removal
  (R-10.7, R-10.8): an expired record is rejected while still physically present.
* ``put_if_version`` is an optimistic-concurrency conditional write: it succeeds only
  when the stored ``version`` equals ``expected`` and then persists the record with its
  ``version`` incremented and ``expires_at`` refreshed to ``updated_at + TTL``. A stale
  ``expected`` raises :class:`VersionConflict` and changes nothing.
* ``delete`` permanently removes the record (R-10.5, R-10.6); deleting an absent record
  is a no-op.

Dependencies (clock and id generator) are injected so tests can substitute them.
Session IDs come from :func:`secrets.token_urlsafe`, giving at least 128 bits of
randomness that is not derived from any input (R-01.2).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from app.domain.models import SessionRecord

# token_urlsafe(nbytes) draws nbytes random bytes; 32 bytes = 256 bits of entropy,
# comfortably above the 128-bit floor required by R-01.2.
SESSION_ID_ENTROPY_BYTES = 32

# Session TTL applied to expires_at on every persist (R-10.7). Kept here as the store's
# own default; callers may pass an explicit ttl to override (config is the source of truth).
DEFAULT_TTL = timedelta(hours=24)


def new_session_id() -> str:
    """Return a fresh opaque Session_ID with >=128 bits of randomness (R-01.2).

    Uses ``secrets.token_urlsafe(32)``. The value is independent of any request input,
    so creating two sessions with identical inputs yields different IDs.
    """
    return secrets.token_urlsafe(SESSION_ID_ENTROPY_BYTES)


class Clock(Protocol):
    """Injectable time source so expiry is deterministic in tests."""

    def now(self) -> datetime: ...


class SystemClock:
    """Default clock returning timezone-aware UTC time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


# An id generator is any zero-argument callable returning a Session_ID.
IdGenerator = Callable[[], str]


class SessionStoreError(Exception):
    """Base class for Session_Store errors; carries an API ``code``."""

    code: str

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class NotFound(SessionStoreError):
    """Raised when a Session_ID is absent (maps to HTTP 404)."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session not found: {session_id!r}", code="not_found")
        self.session_id = session_id


class Expired(SessionStoreError):
    """Raised when a record is read at or after ``expires_at`` (maps to HTTP 410)."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session expired: {session_id!r}", code="expired")
        self.session_id = session_id


class VersionConflict(SessionStoreError):
    """Raised when a conditional write sees an unexpected ``version`` (maps to HTTP 409)."""

    def __init__(self, session_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"version conflict for {session_id!r}: expected {expected}, found {actual}",
            code="version_conflict",
        )
        self.session_id = session_id
        self.expected = expected
        self.actual = actual


class AlreadyExists(SessionStoreError):
    """Raised when ``create`` is called with an existing Session_ID (maps to HTTP 409)."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session already exists: {session_id!r}", code="already_exists")
        self.session_id = session_id


@runtime_checkable
class SessionStore(Protocol):
    """Design's SessionStore Protocol (create, get, put_if_version, delete)."""

    def create(self, s: SessionRecord) -> None: ...

    def get(self, session_id: str, now: datetime) -> SessionRecord: ...

    def put_if_version(self, s: SessionRecord, expected: int) -> None: ...

    def delete(self, session_id: str) -> None: ...


def _refreshed(s: SessionRecord, version: int, ttl: timedelta) -> SessionRecord:
    """Return a copy of ``s`` with ``version`` set and ``expires_at = updated_at + ttl``.

    Centralizes the invariant that every persist refreshes the TTL window off the
    record's ``updated_at`` (R-10.7).
    """
    return s.model_copy(update={"version": version, "expires_at": s.updated_at + ttl})


class InMemorySessionStore:
    """Dict-backed Session_Store for local development and tests (design: in-memory repo).

    Records are stored as independent copies so external mutation of a returned record
    cannot alter stored state. Expiry is evaluated against the ``now`` passed to
    :meth:`get`, never against wall-clock time, keeping behavior deterministic.
    """

    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self._items: dict[str, SessionRecord] = {}
        self._ttl = ttl

    def create(self, s: SessionRecord) -> None:
        if s.session_id in self._items:
            raise AlreadyExists(s.session_id)
        self._items[s.session_id] = _refreshed(s, s.version, self._ttl)

    def get(self, session_id: str, now: datetime) -> SessionRecord:
        record = self._items.get(session_id)
        if record is None:
            raise NotFound(session_id)
        # Reject expired records BEFORE any TTL removal: the record is still present
        # here, yet a read at/after expires_at must fail (R-10.8).
        if now >= record.expires_at:
            raise Expired(session_id)
        return record.model_copy(deep=True)

    def put_if_version(self, s: SessionRecord, expected: int) -> None:
        current = self._items.get(s.session_id)
        if current is None:
            raise NotFound(s.session_id)
        if current.version != expected:
            raise VersionConflict(s.session_id, expected, current.version)
        self._items[s.session_id] = _refreshed(s, expected + 1, self._ttl)

    def delete(self, session_id: str) -> None:
        self._items.pop(session_id, None)


class DynamoDBSessionStore:
    """DynamoDB-backed Session_Store (table ``InvisibleClassroomSessions``, TTL ``expires_at``).

    Partition key is ``session_id``. ``create`` and ``put_if_version`` use conditional
    expressions so inserts and version transitions are atomic under retries. ``expires_at``
    is stored as a Unix epoch integer for DynamoDB TTL and refreshed on every persist
    (R-10.7). Reads compare ``expires_at`` to the injected clock value and reject expired
    records before TTL removal ever runs (R-10.8); DynamoDB TTL deletion is asynchronous
    and may lag, so this check is the authoritative gate.

    ``boto3`` is imported lazily so the in-memory path and contract tests do not require
    it. A ready table resource may be injected for tests; otherwise one is built from the
    region.
    """

    TABLE_NAME = "InvisibleClassroomSessions"

    def __init__(
        self,
        table: object | None = None,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        ttl: timedelta = DEFAULT_TTL,
    ) -> None:
        self._ttl = ttl
        if table is not None:
            self._table = table
            return
        import boto3  # lazy: only for the real backend

        resource = boto3.resource("dynamodb", region_name=region_name, endpoint_url=endpoint_url)
        self._table = resource.Table(self.TABLE_NAME)

    def create(self, s: SessionRecord) -> None:
        record = _refreshed(s, s.version, self._ttl)
        try:
            self._table.put_item(  # type: ignore[attr-defined]
                Item=_to_item(record),
                ConditionExpression="attribute_not_exists(session_id)",
            )
        except Exception as exc:  # noqa: BLE001 - normalize the conditional-check failure
            if _is_conditional_failure(exc):
                raise AlreadyExists(s.session_id) from exc
            raise

    def get(self, session_id: str, now: datetime) -> SessionRecord:
        response = self._table.get_item(Key={"session_id": session_id})  # type: ignore[attr-defined]
        item = response.get("Item")
        if item is None:
            raise NotFound(session_id)
        record = _from_item(item)
        if now >= record.expires_at:
            raise Expired(session_id)
        return record

    def put_if_version(self, s: SessionRecord, expected: int) -> None:
        record = _refreshed(s, expected + 1, self._ttl)
        try:
            self._table.put_item(  # type: ignore[attr-defined]
                Item=_to_item(record),
                ConditionExpression="session_id = :sid AND version = :expected",
                ExpressionAttributeValues={":sid": s.session_id, ":expected": expected},
            )
        except Exception as exc:  # noqa: BLE001 - normalize the conditional-check failure
            if _is_conditional_failure(exc):
                # Either the record is gone or the version moved; disambiguate for callers.
                response = self._table.get_item(Key={"session_id": s.session_id})  # type: ignore[attr-defined]
                item = response.get("Item")
                if item is None:
                    raise NotFound(s.session_id) from exc
                actual = int(item.get("version", -1))
                raise VersionConflict(s.session_id, expected, actual) from exc
            raise

    def delete(self, session_id: str) -> None:
        self._table.delete_item(Key={"session_id": session_id})  # type: ignore[attr-defined]


def _to_item(record: SessionRecord) -> dict[str, object]:
    """Serialize a record to a DynamoDB item.

    ``expires_at`` is written as a Unix epoch integer so DynamoDB TTL can act on it; the
    remaining fields are stored as a JSON-compatible document. Only ``SessionRecord``
    attributes are serialized, so no forbidden attribute can reach the table (R-10.1).
    """
    data = record.model_dump(mode="json")
    data["expires_at_epoch"] = int(record.expires_at.timestamp())
    return data


def _from_item(item: dict[str, object]) -> SessionRecord:
    """Deserialize a DynamoDB item into a ``SessionRecord``.

    The epoch TTL mirror is dropped; ``expires_at`` is reconstructed from the ISO field.
    """
    data = dict(item)
    data.pop("expires_at_epoch", None)
    return SessionRecord.model_validate(data)


def _is_conditional_failure(exc: Exception) -> bool:
    """Return whether ``exc`` is a DynamoDB conditional-check failure.

    Matched structurally (by error code) to avoid importing botocore just for the type.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error", {})
        code = error.get("Code") if isinstance(error, dict) else None
        return bool(code == "ConditionalCheckFailedException")
    return type(exc).__name__ == "ConditionalCheckFailedException"
