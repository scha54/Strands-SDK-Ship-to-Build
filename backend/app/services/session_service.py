"""Session service: creation, capability tokens and lifecycle (R-01, R-08.3, R-10; NFR-01/02/08).

This service owns the Session lifecycle operations the API exposes, holding no HTTP concerns
itself so it stays unit-testable with an injected store and clock:

* :meth:`SessionService.create` validates and normalizes the request, mints a Session_ID and a
  high-entropy Capability_Token, persists a new ``SessionRecord`` storing only the *hash* of the
  token (never the token itself, R-10.1) and returns both the ID and the plaintext token to the
  caller exactly once. Creation performs zero model/Bedrock calls (R-01.6) and makes no partial
  write: if normalization fails the store is never touched, so a failed creation leaves no record
  (R-01.4, R-01.6).
* :meth:`SessionService.get` reads a Session, surfacing the store's :class:`NotFound` (404,
  R-10.6) and :class:`Expired` (410, R-10.8) as-is.
* :meth:`SessionService.stop` transitions any non-terminal Session to ``STOPPED`` so later
  answer/hint/advance writes are rejected while the data stays readable for review and delete
  (R-08.3). Stop is idempotent: stopping an already-stopped Session is a no-op success.
* :meth:`SessionService.end` performs a normal end (``ENDED``), enabling delete (R-10.4).
* :meth:`SessionService.delete` permanently removes the Session (R-10.5); subsequent reads or
  deletes return :class:`NotFound` (404, R-10.6).

The Capability_Token is a URL-safe bearer secret with at least 256 bits of entropy. Only its
SHA-256 hash is persisted; authorization compares the presented token's hash against the stored
hash in constant time (see :func:`verify_token`) to avoid leaking information through timing.
The Session_ID is generated independently of any request input (R-01.2) by the store's
``new_session_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.adapters.session_store import (
    DEFAULT_TTL,
    Clock,
    IdGenerator,
    SessionStore,
    SystemClock,
    new_session_id,
)
from app.domain.models import (
    CreateSessionRequest,
    SessionRecord,
)
from app.domain.state_machine import SessionState, validate_transition
from app.services.normalizer import normalize_objects

# Capability_Token entropy. 32 bytes = 256 bits, well above a safe bearer-secret floor and
# independent of any request input (session theft control, design section 8).
CAPABILITY_TOKEN_ENTROPY_BYTES = 32


def new_capability_token() -> str:
    """Return a fresh high-entropy URL-safe Capability_Token (design: session theft control)."""
    return secrets.token_urlsafe(CAPABILITY_TOKEN_ENTROPY_BYTES)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in place of the plaintext token (R-10.1).

    Only this digest is persisted; the plaintext token is returned to the caller once at
    creation and never stored, so a store compromise does not yield usable tokens.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(presented_token: str, stored_hash: str) -> bool:
    """Return whether ``presented_token`` matches ``stored_hash`` in constant time.

    The presented token is hashed and compared to the stored hash with
    :func:`hmac.compare_digest`, so comparison time does not depend on how many leading
    characters match (defends against timing side channels on the capability token).
    """
    return hmac.compare_digest(hash_token(presented_token), stored_hash)


@dataclass(frozen=True)
class CreatedSession:
    """Result of :meth:`SessionService.create`.

    Carries the opaque ``session_id`` and the plaintext ``capability_token`` returned to the
    caller exactly once. The token is never persisted in plaintext (only its hash is).
    """

    session_id: str
    capability_token: str
    record: SessionRecord


class SessionService:
    """Session lifecycle operations over an injected :class:`SessionStore` and clock.

    The store, clock and id/token generators are injected so creation IDs, expiry and tokens
    are deterministic in tests and so the real DynamoDB backend can be swapped in without
    changing this service (design: dependency injection for model/store/clock).
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        clock: Clock | None = None,
        ttl: timedelta = DEFAULT_TTL,
        id_generator: IdGenerator = new_session_id,
        token_generator: IdGenerator = new_capability_token,
    ) -> None:
        self._store = store
        self._clock = clock or SystemClock()
        self._ttl = ttl
        self._new_id = id_generator
        self._new_token = token_generator

    def _now(self) -> datetime:
        return self._clock.now()

    def create(self, request: CreateSessionRequest) -> CreatedSession:
        """Validate, normalize and persist a new Session; return its ID and token (R-01).

        Normalization runs before any write, so a normalization failure (``NormalizationError``)
        propagates with the store untouched — a failed creation leaves no record (R-01.4,
        R-01.6). No model/Bedrock call is made here (R-01.6). On success exactly one record is
        created, storing only the token hash (R-10.1), and the plaintext token is returned once.
        """
        # Normalize first. If this raises, we have written nothing (R-01.4, R-01.6).
        inventory = normalize_objects(list(request.objects))

        now = self._now()
        token = self._new_token()
        record = SessionRecord(
            session_id=self._new_id(),
            token_hash=hash_token(token),
            state=SessionState.CREATED.value,
            age_band=request.age_band,
            subject=request.subject,
            language=request.language,
            objects=inventory.items,
            activity_status=[],
            answers=[],
            current_index=0,
            stage_events=[],
            idempotency=[],
            generation_count=0,
            created_at=now,
            updated_at=now,
            expires_at=now + self._ttl,  # store refreshes to updated_at + ttl on persist
            version=0,
        )
        self._store.create(record)
        # Re-read so the returned record reflects the store's persisted TTL/version.
        stored = self._store.get(record.session_id, now)
        return CreatedSession(
            session_id=stored.session_id,
            capability_token=token,
            record=stored,
        )

    def get(self, session_id: str) -> SessionRecord:
        """Return the Session, raising NotFound (404) or Expired (410) from the store."""
        return self._store.get(session_id, self._now())

    def stop(self, session_id: str) -> SessionRecord:
        """Transition the Session to ``STOPPED`` so later writes are rejected (R-08.3).

        Stop is reachable from every non-terminal state. It is idempotent: an already-stopped
        Session returns unchanged. Data stays readable for review and delete — only writes
        (answer/hint/advance) are blocked afterward, enforced by the state machine guard.
        """
        return self._transition(session_id, SessionState.STOPPED, idempotent=True)

    def end(self, session_id: str) -> SessionRecord:
        """Transition an active Session to ``ENDED``, enabling delete (R-10.4)."""
        return self._transition(session_id, SessionState.ENDED, idempotent=True)

    def delete(self, session_id: str) -> None:
        """Permanently delete the Session (R-10.5).

        Reads the Session first so a delete on an absent/expired Session surfaces NotFound
        (404, R-10.6) or Expired (410, R-10.8) rather than silently succeeding. A subsequent
        read or delete then returns NotFound (404, R-10.6).
        """
        # Confirm existence (and non-expiry) before removing, so the caller gets 404/410.
        self._store.get(session_id, self._now())
        self._store.delete(session_id)

    def _transition(
        self, session_id: str, target: SessionState, *, idempotent: bool
    ) -> SessionRecord:
        """Apply a lifecycle transition under optimistic concurrency.

        Reads the current record (404/410 via the store), validates the state-machine
        transition (illegal -> 409 ``invalid_state``) and writes the new state with
        ``put_if_version`` so concurrent writers cannot clobber each other. When
        ``idempotent`` and the Session is already in ``target``, returns it unchanged.
        """
        now = self._now()
        record = self._store.get(session_id, now)
        current = SessionState(record.state)
        if idempotent and current is target:
            return record
        validate_transition(current, target)
        updated = record.model_copy(update={"state": target.value, "updated_at": now})
        self._store.put_if_version(updated, record.version)
        return self._store.get(session_id, now)
