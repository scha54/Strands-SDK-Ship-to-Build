"""API middleware tests: body size, concurrency, rate limit, correlation ID (R-11.4; NFR-05).

Each limit (body size 413, concurrency 429, rate limit 429) must return the right status
AND name the limit, and must reject in middleware before any handler so the Session_Store is
never written (R-11.4). A spy store records every ``create``/``put_if_version`` call so the
tests can assert zero writes on a rejected request. The clock and client identifier are
injected for deterministic rate-limit windows.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from app.api.errors import CORRELATION_ID_HEADER
from app.api.middleware import add_request_limit_middleware
from app.config import Settings
from app.main import create_app
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send


def _http_scope(path: str) -> Scope:
    """Minimal ASGI HTTP scope for driving the middleware directly."""
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }


async def _empty_receive() -> Message:
    """A receive that yields an empty, final request body chunk."""
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send_ok(send: Send) -> None:
    """Send a trivial 200 response from an inner ASGI app."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


class _Collector:
    """Captures the status and JSON body an ASGI app sends."""

    def __init__(self) -> None:
        self.status = 0
        self._body = b""

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.status = int(message["status"])
        elif message["type"] == "http.response.body":
            self._body += message.get("body", b"")

    @property
    def body(self) -> dict[str, object]:
        parsed: dict[str, object] = json.loads(self._body.decode("utf-8")) if self._body else {}
        return parsed

    def detail(self, key: str) -> object:
        details = self.body["details"]
        assert isinstance(details, dict)
        return details[key]


def _collect_sends() -> _Collector:
    return _Collector()


class SpyStore:
    """A Session_Store spy that counts writes without persisting anything.

    Used to prove that a middleware rejection causes no ``create``/``put_if_version`` call
    (R-11.4: limit rejections have no side effects).
    """

    def __init__(self) -> None:
        self.create_calls = 0
        self.put_calls = 0
        self.delete_calls = 0

    def create(self, _record: object) -> None:
        self.create_calls += 1

    def put_if_version(self, _record: object, _expected: int) -> None:
        self.put_calls += 1

    def delete(self, _session_id: str) -> None:
        self.delete_calls += 1

    @property
    def writes(self) -> int:
        return self.create_calls + self.put_calls + self.delete_calls


class FrozenClock:
    """A controllable clock for deterministic rate-limit windows."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def build_app(
    settings: Settings,
    *,
    clock: FrozenClock | None = None,
    store: SpyStore | None = None,
) -> tuple[FastAPI, SpyStore]:
    """Build an app with a spy-store-backed write route."""
    spy = store or SpyStore()

    app = create_app(
        settings,
        clock=clock,
        # Single, constant client so the rate limiter treats the test as one client.
        client_identifier=lambda _scope: "test-client",
    )

    @app.post("/write")
    async def write(request: Request) -> dict[str, str]:
        # A handler that would write to the store if it ran. If a limit rejects the request
        # in middleware, this never executes and spy.writes stays 0.
        await request.body()
        spy.create(object())
        return {"status": "written"}

    return app, spy


# --- body size (413) ------------------------------------------------------------------------


def test_body_over_limit_returns_413_and_names_limit_with_no_write() -> None:
    """Body over the limit -> 413 naming the limit, no store write. Validates: R-11.4."""
    settings = Settings(max_request_body_bytes=100)
    app, spy = build_app(settings)
    client = TestClient(app)

    resp = client.post("/write", content=b"x" * 500)

    assert resp.status_code == 413
    body = resp.json()
    assert body["code"] == "request_body_too_large"
    assert body["details"]["limit"] == "request_body_bytes"
    assert body["details"]["limit_bytes"] == 100
    assert spy.writes == 0  # rejected before the handler ran


def test_body_at_limit_is_allowed() -> None:
    """A body within the limit reaches the handler. Validates: R-11.4 boundary."""
    settings = Settings(max_request_body_bytes=100)
    app, spy = build_app(settings)
    client = TestClient(app)

    resp = client.post("/write", content=b"x" * 50)

    assert resp.status_code == 200
    assert spy.create_calls == 1


# --- rate limit (429) -----------------------------------------------------------------------


def test_rate_limit_returns_429_and_names_limit_with_no_write() -> None:
    """Exceeding the per-client rate -> 429 naming the limit, no write. Validates: R-11.4."""
    settings = Settings(rate_limit_per_minute=3)
    clock = FrozenClock()
    app, spy = build_app(settings, clock=clock)
    client = TestClient(app)

    statuses = [client.post("/write", content=b"ok").status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    rejected = client.post("/write", content=b"ok")
    assert rejected.status_code == 429
    body = rejected.json()
    assert body["code"] == "rate_limit_exceeded"
    assert body["details"]["limit"] == "rate_limit_per_minute"
    assert body["details"]["limit_value"] == 3
    # Exactly the 3 admitted requests wrote; the rejected ones did not.
    assert spy.create_calls == 3


def test_rate_window_rolls_forward_with_the_clock() -> None:
    """After the window elapses the client may send again. Validates: R-11.4."""
    settings = Settings(rate_limit_per_minute=1)
    clock = FrozenClock()
    app, _spy = build_app(settings, clock=clock)
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").status_code == 429  # within the window
    clock.advance(61)
    assert client.get("/healthz").status_code == 200  # window rolled over


# --- concurrency (429) ----------------------------------------------------------------------


async def test_concurrency_cap_returns_429_and_names_limit_with_no_write() -> None:
    """Exceeding the in-flight cap -> 429 naming the limit, no write. Validates: R-11.4.

    The middleware is driven directly at the ASGI level with a slow inner app. One request
    is held in-flight (occupying the single slot) while a second is issued concurrently; the
    second is rejected before the inner app runs, so the spy store records no write. This
    exercises the real concurrency counter deterministically without threads.
    """
    settings = Settings(max_concurrent_requests=1, rate_limit_per_minute=1000)
    spy = SpyStore()
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        # Represents a handler that writes to the store. It stays in-flight until released.
        started.set()
        await release.wait()
        spy.create(object())
        await _send_ok(send)

    middleware = add_request_limit_middleware(
        slow_inner_app, settings, client_identifier=lambda _s: "c"
    )

    first = asyncio.create_task(
        middleware(_http_scope("/block"), _empty_receive, _collect_sends().send)
    )
    await started.wait()  # the first request now occupies the only in-flight slot

    collected = _collect_sends()
    await middleware(_http_scope("/write"), _empty_receive, collected.send)

    assert collected.status == 429
    assert collected.body["code"] == "concurrency_limit_exceeded"
    assert collected.detail("limit") == "max_concurrent_requests"
    assert spy.writes == 0  # the rejected request never reached the inner app

    release.set()
    await first


# --- correlation ID -------------------------------------------------------------------------


def test_correlation_id_generated_and_echoed() -> None:
    """A correlation ID is generated and echoed on the response. Validates: R-11.3."""
    app, _spy = build_app(Settings())
    client = TestClient(app)

    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER)


def test_incoming_correlation_id_is_honored() -> None:
    """An incoming correlation header is honored and echoed back. Validates: R-11.3."""
    app, _spy = build_app(Settings())
    client = TestClient(app)

    resp = client.get("/healthz", headers={CORRELATION_ID_HEADER: "corr-123"})

    assert resp.headers.get(CORRELATION_ID_HEADER) == "corr-123"


def test_correlation_id_present_on_limit_rejection() -> None:
    """Even a rejected request carries a correlation ID. Validates: R-11.3, R-11.4."""
    settings = Settings(max_request_body_bytes=10)
    app, _spy = build_app(settings)
    client = TestClient(app)

    resp = client.post("/write", content=b"x" * 100)

    assert resp.status_code == 413
    assert resp.headers.get(CORRELATION_ID_HEADER)
    assert resp.json()["correlation_id"]


def test_client_identifier_default_uses_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default client identifier reads the ASGI scope without error. Validates: R-11.4."""
    from app.api.middleware import _client_identity

    scope: Scope = {"type": "http", "headers": [], "client": ("203.0.113.5", 51234)}
    assert _client_identity(scope) == "203.0.113.5"
    forwarded: Scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"198.51.100.2, 10.0.0.1")],
    }
    assert _client_identity(forwarded) == "198.51.100.2"
