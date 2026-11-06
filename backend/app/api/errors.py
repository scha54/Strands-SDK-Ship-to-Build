"""ApiError mapping for store/domain exceptions and limit violations (R-11.4; NFR-05).

Every error leaves the API as the design's ``{code, message, correlation_id, details?}``
body (``app.domain.models.ApiError``) with no raw exception text, prompt text or model
reasoning. The status mapping follows the design's table:

* 401 ``unauthorized`` — missing/invalid capability token on a session-specific route.
* 404 ``not_found`` — session absent or already deleted.
* 410 ``expired`` — read at or after ``expires_at``.
* 409 ``version_conflict`` / ``already_exists`` / ``invalid_state`` / ``session_stopped`` /
  ``idempotency_key_conflict`` — invalid state, stopped session or idempotency conflict,
  each with a distinct ``code``.
* 413 ``request_body_too_large`` — body over the configured limit (R-11.4); the limit that
  was exceeded is named in ``code``/``message``/``details``.
* 422 ``validation_error`` — request validation, listing each invalid field.
* 429 ``rate_limit_exceeded`` / ``concurrency_limit_exceeded`` — a per-client rate or the
  in-flight concurrency cap was exceeded (R-11.4); the limit is named in
  ``code``/``message``/``details``.
* 503 ``dependency_unavailable`` — a required dependency is unavailable.

Limit rejections (413/429) are produced by the middleware *before* any route handler runs,
so they never touch the Session_Store (R-11.4). This module provides the exception types the
middleware raises, the mapping from store/domain exceptions to HTTP statuses, and the
FastAPI exception handlers that render every error through ``ApiError``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.adapters.session_store import (
    AlreadyExists,
    Expired,
    NotFound,
    SessionStoreError,
    VersionConflict,
)
from app.domain.models import ApiError
from app.domain.state_machine import InvalidStateTransition, SessionStoppedError, StateMachineError
from app.services.lesson_service import LessonError

# Header that carries the correlation ID on every request and response (R-11.3).
CORRELATION_ID_HEADER = "X-Correlation-ID"
# Request state attribute the middleware sets and handlers read.
CORRELATION_ID_STATE_ATTR = "correlation_id"

# HTTP status codes used by the mapping (kept local to avoid importing http.HTTPStatus names
# at call sites and to document the design's table in one place).
HTTP_401_UNAUTHORIZED = 401
HTTP_404_NOT_FOUND = 404
HTTP_409_CONFLICT = 409
HTTP_410_GONE = 410
HTTP_413_REQUEST_ENTITY_TOO_LARGE = 413
HTTP_422_UNPROCESSABLE_ENTITY = 422
HTTP_429_TOO_MANY_REQUESTS = 429
HTTP_503_SERVICE_UNAVAILABLE = 503


class LimitExceeded(Exception):
    """Base class for request-limit violations rejected in middleware (R-11.4).

    Each subclass names, in ``code`` and ``details['limit']``, exactly which limit was
    exceeded so the error body identifies it without exposing internals. These are raised
    by the middleware before any handler runs, so no Session_Store write occurs.
    """

    status_code: int
    code: str

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BodyTooLarge(LimitExceeded):
    """Request body exceeds ``max_request_body_bytes`` (HTTP 413, R-11.4)."""

    status_code = HTTP_413_REQUEST_ENTITY_TOO_LARGE
    code = "request_body_too_large"

    def __init__(self, limit_bytes: int, observed_bytes: int | None = None) -> None:
        details: dict[str, Any] = {"limit": "request_body_bytes", "limit_bytes": limit_bytes}
        if observed_bytes is not None:
            details["observed_bytes"] = observed_bytes
        super().__init__(
            f"request body exceeds the {limit_bytes}-byte limit",
            details=details,
        )


class ConcurrencyLimitExceeded(LimitExceeded):
    """Too many in-flight requests (HTTP 429, R-11.4)."""

    status_code = HTTP_429_TOO_MANY_REQUESTS
    code = "concurrency_limit_exceeded"

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"too many concurrent requests; the in-flight limit is {limit}",
            details={"limit": "max_concurrent_requests", "limit_value": limit},
        )


class RateLimitExceeded(LimitExceeded):
    """Per-client request rate exceeded (HTTP 429, R-11.4)."""

    status_code = HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limit_exceeded"

    def __init__(self, limit_per_minute: int) -> None:
        super().__init__(
            f"rate limit exceeded; at most {limit_per_minute} requests per minute are allowed",
            details={"limit": "rate_limit_per_minute", "limit_value": limit_per_minute},
        )


class Unauthorized(Exception):
    """Missing or invalid capability token on a session-specific route (HTTP 401).

    Raised by the capability-token dependency (``app/api/auth.py``) when the
    ``Authorization: Bearer`` header is absent/malformed or the presented token does not
    match the stored hash. The message is deliberately generic so it never reveals whether
    the Session_ID exists or why the token failed (session-theft control, design section 8).
    """

    status_code = HTTP_401_UNAUTHORIZED
    code = "unauthorized"

    def __init__(self, message: str = "missing or invalid capability token") -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] | None = None


class DependencyUnavailable(Exception):
    """A required dependency is unavailable (HTTP 503).

    ``dependencies`` names the unavailable dependency or dependencies so ``/readyz`` and
    other callers can report which one is down (R-11.6) without leaking internals.
    """

    status_code = HTTP_503_SERVICE_UNAVAILABLE
    code = "dependency_unavailable"

    def __init__(self, dependencies: list[str]) -> None:
        joined = ", ".join(dependencies) if dependencies else "unknown"
        super().__init__(f"dependency unavailable: {joined}")
        self.message = f"dependency unavailable: {joined}"
        self.dependencies = dependencies
        self.details: dict[str, Any] = {"unavailable": dependencies}


# Store-exception code -> HTTP status. Each store error carries a ``code`` already; the
# mapping only decides the status, so the distinct ``code`` values flow through unchanged.
_STORE_STATUS_BY_TYPE: dict[type[SessionStoreError], int] = {
    NotFound: HTTP_404_NOT_FOUND,
    Expired: HTTP_410_GONE,
    VersionConflict: HTTP_409_CONFLICT,
    AlreadyExists: HTTP_409_CONFLICT,
}

# State-machine errors both map to 409 with their own distinct codes.
_STATE_MACHINE_STATUS_BY_TYPE: dict[type[StateMachineError], int] = {
    InvalidStateTransition: HTTP_409_CONFLICT,
    SessionStoppedError: HTTP_409_CONFLICT,
}


def status_for_store_error(exc: SessionStoreError) -> int:
    """Return the HTTP status for a Session_Store error (404/409/410).

    The idempotency conflict (``IdempotencyKeyConflict``) subclasses ``SessionStoreError``
    but is not in the type table; it falls through to 409, matching the design.
    """
    for exc_type, status in _STORE_STATUS_BY_TYPE.items():
        if isinstance(exc, exc_type):
            return status
    return HTTP_409_CONFLICT


def correlation_id_of(request: Request) -> str:
    """Return the correlation ID the middleware attached to ``request`` (R-11.3).

    Falls back to an empty string only if the middleware did not run (it always runs in the
    wired app), so handlers can always echo a value.
    """
    return str(getattr(request.state, CORRELATION_ID_STATE_ATTR, "") or "")


def _render(
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    details: dict[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    """Build a JSONResponse carrying an ``ApiError`` body and the correlation header."""
    body = ApiError(code=code, message=message, correlation_id=correlation_id, details=details)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        headers={CORRELATION_ID_HEADER: correlation_id},
    )


async def _limit_exceeded_handler(request: Request, exc: LimitExceeded) -> JSONResponse:
    """Render a 413/429 limit rejection. The limit is named in code/message/details."""
    return _render(
        exc.status_code,
        exc.code,
        exc.message,
        correlation_id_of(request),
        details=exc.details,
    )


async def _unauthorized_handler(request: Request, exc: Unauthorized) -> JSONResponse:
    """Render a 401 with a generic message that never leaks token or session details."""
    response = _render(
        exc.status_code,
        exc.code,
        exc.message,
        correlation_id_of(request),
        details=exc.details,
    )
    # Signal the expected scheme without revealing anything about the token or session.
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


async def _dependency_unavailable_handler(
    request: Request, exc: DependencyUnavailable
) -> JSONResponse:
    """Render a 503 naming the unavailable dependency (R-11.6)."""
    return _render(
        exc.status_code,
        exc.code,
        exc.message,
        correlation_id_of(request),
        details=exc.details,
    )


async def _store_error_handler(request: Request, exc: SessionStoreError) -> JSONResponse:
    """Render a store error (404/409/410) using its own distinct ``code``."""
    return _render(
        status_for_store_error(exc),
        exc.code,
        str(exc),
        correlation_id_of(request),
    )


async def _state_machine_error_handler(request: Request, exc: StateMachineError) -> JSONResponse:
    """Render a state-machine error (409) using its distinct ``code``."""
    return _render(
        HTTP_409_CONFLICT,
        exc.code,
        str(exc),
        correlation_id_of(request),
    )


async def _lesson_error_handler(request: Request, exc: LessonError) -> JSONResponse:
    """Render a lesson-service error (cap reached, PII removal required, no usable objects)."""
    return _render(exc.status_code, exc.code, exc.message, correlation_id_of(request))


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Render a 422 listing each invalid field (design status mapping).

    Field locations and messages come from Pydantic; no raw request body or prompt text is
    echoed back, only the field path and the validator message.
    """
    fields = [
        {"field": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "")}
        for err in exc.errors()
    ]
    return _render(
        HTTP_422_UNPROCESSABLE_ENTITY,
        "validation_error",
        "request validation failed",
        correlation_id_of(request),
        details=fields,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the exception handlers that render every error as an ``ApiError``.

    Covers limit violations (413/429), dependency unavailability (503), Session_Store errors
    (404/409/410), state-machine errors (409) and request validation (422). Raw exceptions,
    prompts and model reasoning are never returned (design error-response contract).
    """
    app.add_exception_handler(LimitExceeded, _limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Unauthorized, _unauthorized_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DependencyUnavailable, _dependency_unavailable_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SessionStoreError, _store_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(LessonError, _lesson_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StateMachineError, _state_machine_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
