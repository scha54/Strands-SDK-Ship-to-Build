"""Request-limit and correlation middleware, enforced before any handler (R-11.4; NFR-05).

This is a pure-ASGI middleware so every check runs *before* routing — a rejected request
therefore never reaches a route handler and never touches the Session_Store (R-11.4). The
middleware enforces, in order:

1. **Correlation ID** — honor an incoming ``X-Correlation-ID`` header or generate a fresh
   one; attach it to ``request.state`` and echo it on every response and error (R-11.3).
2. **Body-size limit** — reject bodies over ``settings.max_request_body_bytes`` with HTTP
   413, naming the ``request_body_bytes`` limit. Both a declared ``Content-Length`` and the
   actually-streamed byte count are checked, so a lying or absent header cannot bypass it.
3. **Concurrency cap** — reject when more than ``settings.max_concurrent_requests`` requests
   are already in flight with HTTP 429, naming the ``max_concurrent_requests`` limit.
4. **Per-client rate limit** — reject when a client exceeds ``settings.rate_limit_per_minute``
   within a rolling 60-second window with HTTP 429, naming the ``rate_limit_per_minute``
   limit.

Rejections are rendered through the same ``ApiError`` shape as the exception handlers, with
the limit named in ``code``/``message``/``details`` (R-11.4). The clock and client-identity
function are injectable so rate-limit windows are deterministic in tests.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_STATE_ATTR,
    BodyTooLarge,
    ConcurrencyLimitExceeded,
    LimitExceeded,
    RateLimitExceeded,
)
from app.config import Settings
from app.domain.models import ApiError

# Rolling window for the per-client rate limit (R-11.4: 60 per minute).
RATE_WINDOW_SECONDS = 60.0

# Type aliases for the injected dependencies.
Clock = Callable[[], datetime]
ClientIdentifier = Callable[[Scope], str]


def _iter_headers(scope: Scope) -> list[tuple[bytes, bytes]]:
    """Return the ASGI raw header list, typed, from the loosely-typed scope mapping."""
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    return headers


def default_clock() -> datetime:
    """Default clock returning timezone-aware UTC time."""
    return datetime.now(UTC)


# Private aliases used within this module and by tests.
_system_clock = default_clock


def default_client_identifier(scope: Scope) -> str:
    """Identify a client for rate limiting.

    Prefers a forwarded-for client hint, then the peer address. Absent both (e.g. in-process
    test transports), returns a constant so limits still apply per the test's single client.
    """
    for key, value in _iter_headers(scope):
        if key.decode("latin-1").lower() == "x-forwarded-for":
            first = value.decode("latin-1").split(",")[0].strip()
            if first:
                return first
    client = scope.get("client")
    if client:
        return str(client[0])
    return "anonymous"


# Private alias used within this module and by tests.
_client_identity = default_client_identifier


class _RateLimiter:
    """Rolling-window per-client counter (R-11.4).

    Keeps the timestamps of each client's recent requests and admits a new request only when
    fewer than ``limit_per_minute`` fall inside the trailing ``RATE_WINDOW_SECONDS``. Using a
    rolling window (not a fixed bucket) prevents a burst straddling a boundary from doubling
    the effective rate. The injected clock keeps windows deterministic in tests.
    """

    def __init__(self, limit_per_minute: int, clock: Clock) -> None:
        self._limit = limit_per_minute
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check_and_record(self, client: str) -> None:
        """Admit one request for ``client`` or raise :class:`RateLimitExceeded`."""
        now = self._clock().timestamp()
        cutoff = now - RATE_WINDOW_SECONDS
        hits = self._hits[client]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            raise RateLimitExceeded(self._limit)
        hits.append(now)


class RequestLimitMiddleware:
    """Pure-ASGI middleware enforcing body/concurrency/rate limits and correlation IDs.

    Being pure ASGI, it short-circuits a rejected request with its own response and never
    calls ``app``, guaranteeing no handler runs and no Session_Store write happens on a
    limit rejection (R-11.4).
    """

    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        *,
        clock: Clock = _system_clock,
        client_identifier: ClientIdentifier = _client_identity,
    ) -> None:
        self._app = app
        self._settings = settings
        self._clock = clock
        self._client_identifier = client_identifier
        self._rate_limiter = _RateLimiter(settings.rate_limit_per_minute, clock)
        self._in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        correlation_id = self._resolve_correlation_id(scope)
        # Make the correlation ID available to request.state for handlers (R-11.3).
        scope.setdefault("state", {})[CORRELATION_ID_STATE_ATTR] = correlation_id

        try:
            self._check_content_length(scope)
            self._check_concurrency()
            self._check_rate_limit(scope)
        except LimitExceeded as exc:
            await self._reject(exc, correlation_id, send)
            return

        # Enforce the body-size limit on the actual stream too, so an absent or
        # understated Content-Length cannot smuggle an oversized body past the check.
        guarded_receive, body_error = self._guard_body(receive)

        self._in_flight += 1
        send_wrapper = self._with_correlation_header(send, correlation_id)
        try:
            await self._app(scope, guarded_receive, send_wrapper)
        finally:
            self._in_flight -= 1

        # If the stream exceeded the limit after the app started reading, the oversize is
        # recorded; nothing further is needed because the guarded receive raises to the app,
        # but we keep the hook for clarity/testing of the limit value.
        _ = body_error

    def _resolve_correlation_id(self, scope: Scope) -> str:
        """Honor an incoming correlation header or mint a new UUID4 (R-11.3)."""
        for key, value in _iter_headers(scope):
            if key.decode("latin-1").lower() == CORRELATION_ID_HEADER.lower():
                incoming = value.decode("latin-1").strip()
                if incoming:
                    return incoming
        return str(uuid.uuid4())

    def _check_content_length(self, scope: Scope) -> None:
        """Reject a declared body larger than the limit before reading it (R-11.4)."""
        limit = self._settings.max_request_body_bytes
        for key, value in _iter_headers(scope):
            if key.decode("latin-1").lower() == "content-length":
                try:
                    declared = int(value.decode("latin-1"))
                except ValueError:
                    return
                if declared > limit:
                    raise BodyTooLarge(limit, observed_bytes=declared)
                return

    def _check_concurrency(self) -> None:
        """Reject when the in-flight count is already at the cap (R-11.4)."""
        if self._in_flight >= self._settings.max_concurrent_requests:
            raise ConcurrencyLimitExceeded(self._settings.max_concurrent_requests)

    def _check_rate_limit(self, scope: Scope) -> None:
        """Reject when the per-client rate is exceeded (R-11.4)."""
        self._rate_limiter.check_and_record(self._client_identifier(scope))

    def _guard_body(self, receive: Receive) -> tuple[Receive, dict[str, int]]:
        """Wrap ``receive`` so the streamed body is counted against the limit (R-11.4).

        If the running total exceeds ``max_request_body_bytes`` the wrapper raises
        :class:`BodyTooLarge`; because the limit checks happen before any Session_Store
        write in a handler, an oversize body still produces no side effect.
        """
        limit = self._settings.max_request_body_bytes
        state = {"received": 0}

        async def guarded_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                state["received"] += len(body)
                if state["received"] > limit:
                    raise BodyTooLarge(limit, observed_bytes=state["received"])
            return message

        return guarded_receive, state

    async def _reject(self, exc: LimitExceeded, correlation_id: str, send: Send) -> None:
        """Send the ``ApiError`` rejection response without invoking the app (R-11.4)."""
        body = ApiError(
            code=exc.code,
            message=exc.message,
            correlation_id=correlation_id,
            details=exc.details,
        )
        payload = body.model_dump_json().encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("latin-1")),
            (CORRELATION_ID_HEADER.lower().encode("latin-1"), correlation_id.encode("latin-1")),
        ]
        await send({"type": "http.response.start", "status": exc.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": payload})

    def _with_correlation_header(self, send: Send, correlation_id: str) -> Send:
        """Return a ``send`` that appends the correlation header to the response (R-11.3)."""
        header_name = CORRELATION_ID_HEADER.lower().encode("latin-1")
        header_value = correlation_id.encode("latin-1")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[Any] = list(message.get("headers", []))
                if not any(name.lower() == header_name for name, _ in headers):
                    headers.append((header_name, header_value))
                message = {**message, "headers": headers}
            await send(message)

        return send_wrapper


def add_request_limit_middleware(
    app: ASGIApp,
    settings: Settings,
    *,
    clock: Clock = _system_clock,
    client_identifier: ClientIdentifier = _client_identity,
) -> RequestLimitMiddleware:
    """Build a :class:`RequestLimitMiddleware` wrapping ``app`` with injected dependencies."""
    return RequestLimitMiddleware(
        app, settings, clock=clock, client_identifier=client_identifier
    )
