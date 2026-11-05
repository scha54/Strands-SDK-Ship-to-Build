"""Capability-token authorization dependency for session-specific routes (R-01, R-10; NFR-01).

Every session-specific route requires ``Authorization: Bearer <capability token>``. This module
provides the FastAPI dependency :func:`require_session` that:

1. Extracts the bearer token from the ``Authorization`` header, raising
   :class:`~app.api.errors.Unauthorized` (401) when it is absent or malformed.
2. Loads the Session via the :class:`~app.services.session_service.SessionService`, surfacing the
   store's :class:`NotFound` (404, R-10.6) and :class:`Expired` (410, R-10.8) unchanged.
3. Verifies the presented token against the stored hash in constant time
   (:func:`~app.services.session_service.verify_token`), raising :class:`Unauthorized` (401) on a
   mismatch without revealing whether the Session exists or why the token failed.

The ``SessionService`` is resolved from ``app.state.session_service`` (wired in ``main.py``) so the
store, clock and token generators are injectable for deterministic tests. The resolved
``SessionRecord`` is returned so handlers do not re-read the Session.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Request

from app.api.errors import Unauthorized
from app.domain.models import SessionRecord
from app.services.session_service import SessionService, verify_token

# The scheme prefix we accept on the Authorization header. Comparison is case-insensitive on the
# scheme per RFC 7235, but the token itself is matched exactly.
_BEARER_PREFIX = "bearer "


def get_session_service(request: Request) -> SessionService:
    """Return the ``SessionService`` wired onto ``app.state`` (raises if the app is misconfigured).

    Centralizes DI lookup so routes and the auth dependency share one service instance and tests
    can inject a service built over an in-memory store with a fixed clock.
    """
    service = getattr(request.app.state, "session_service", None)
    if not isinstance(service, SessionService):  # pragma: no cover - configuration guard
        raise RuntimeError("session_service is not configured on app.state")
    return service


def _extract_bearer_token(request: Request) -> str:
    """Return the bearer token from the Authorization header or raise 401.

    A missing header, a non-Bearer scheme or an empty token all yield the same generic
    :class:`Unauthorized` so the response never distinguishes these cases (session-theft control).
    """
    header = request.headers.get("Authorization", "")
    if not header or not header.lower().startswith(_BEARER_PREFIX):
        raise Unauthorized()
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise Unauthorized()
    return token


def require_session(
    request: Request,
    session_id: Annotated[str, Path(min_length=1)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionRecord:
    """FastAPI dependency: authenticate the capability token and return the Session.

    Order matters for privacy and correctness:

    * The token is extracted first (401 on absent/malformed), so unauthenticated callers never
      trigger a store read.
    * The Session is then loaded; :class:`NotFound` (404) and :class:`Expired` (410) from the store
      propagate to the error handlers unchanged (R-10.6, R-10.8).
    * Finally the presented token is compared to the stored hash in constant time; a mismatch is a
      generic 401 (:class:`Unauthorized`) that does not reveal the Session exists.
    """
    token = _extract_bearer_token(request)
    record = service.get(session_id)
    if not verify_token(token, record.token_hash):
        raise Unauthorized()
    return record


# Convenience alias for route signatures: ``session: AuthenticatedSession``.
AuthenticatedSession = Annotated[SessionRecord, Depends(require_session)]
