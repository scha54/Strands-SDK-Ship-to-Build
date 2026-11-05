"""Unit tests for ApiError mapping (R-11.4; NFR-05).

These tests verify that store/domain exceptions and limit violations map to the correct
HTTP statuses (404, 409, 410, 413, 422, 429, 503) and render through the ``ApiError`` shape
``{code, message, correlation_id, details?}`` with no raw exception or prompt text. The
413/429 limit errors must name which limit was exceeded in ``code``/``message``/``details``
(R-11.4).
"""

from __future__ import annotations

import pytest
from app.adapters.session_store import (
    AlreadyExists,
    Expired,
    NotFound,
    VersionConflict,
)
from app.api.errors import (
    BodyTooLarge,
    ConcurrencyLimitExceeded,
    DependencyUnavailable,
    RateLimitExceeded,
    status_for_store_error,
)
from app.domain.models import ApiError
from app.services.idempotency import IdempotencyKeyConflict


def test_store_errors_map_to_expected_statuses() -> None:
    """Store errors map to 404/409/410 with distinct codes. Validates: R-11.4 status mapping."""
    assert status_for_store_error(NotFound("s1")) == 404
    assert status_for_store_error(Expired("s1")) == 410
    assert status_for_store_error(VersionConflict("s1", 1, 2)) == 409
    assert status_for_store_error(AlreadyExists("s1")) == 409


def test_idempotency_conflict_maps_to_409() -> None:
    """Idempotency conflict is a 409 with its own distinct code. Validates: R-11.7, R-11.4."""
    exc = IdempotencyKeyConflict("k1")
    assert status_for_store_error(exc) == 409
    assert exc.code == "idempotency_key_conflict"


def test_body_too_large_names_the_limit() -> None:
    """413 names the body-size limit in code/message/details. Validates: R-11.4."""
    exc = BodyTooLarge(1_048_576, observed_bytes=2_000_000)
    assert exc.status_code == 413
    assert exc.code == "request_body_too_large"
    assert "1048576" in exc.message
    assert exc.details is not None
    assert exc.details["limit"] == "request_body_bytes"
    assert exc.details["limit_bytes"] == 1_048_576
    assert exc.details["observed_bytes"] == 2_000_000


def test_concurrency_limit_names_the_limit() -> None:
    """429 for concurrency names the concurrency limit. Validates: R-11.4."""
    exc = ConcurrencyLimitExceeded(50)
    assert exc.status_code == 429
    assert exc.code == "concurrency_limit_exceeded"
    assert "50" in exc.message
    assert exc.details == {"limit": "max_concurrent_requests", "limit_value": 50}


def test_rate_limit_names_the_limit() -> None:
    """429 for rate limiting names the rate limit. Validates: R-11.4."""
    exc = RateLimitExceeded(60)
    assert exc.status_code == 429
    assert exc.code == "rate_limit_exceeded"
    assert "60" in exc.message
    assert exc.details == {"limit": "rate_limit_per_minute", "limit_value": 60}


def test_body_and_concurrency_codes_are_distinct() -> None:
    """413 and the two 429 codes differ so the client learns which limit. Validates: R-11.4."""
    codes = {
        BodyTooLarge(1).code,
        ConcurrencyLimitExceeded(1).code,
        RateLimitExceeded(1).code,
    }
    assert len(codes) == 3


def test_dependency_unavailable_names_dependencies() -> None:
    """503 names the unavailable dependency. Validates: R-11.6."""
    exc = DependencyUnavailable(["session_store"])
    assert exc.status_code == 503
    assert exc.code == "dependency_unavailable"
    assert "session_store" in exc.message
    assert exc.details == {"unavailable": ["session_store"]}


def test_api_error_body_shape_has_no_raw_exception_fields() -> None:
    """The error body matches the ApiError contract and nothing else. Validates: R-11.4."""
    body = ApiError(code="x", message="m", correlation_id="cid", details={"limit": "y"})
    assert set(body.model_dump().keys()) == {"code", "message", "correlation_id", "details"}


@pytest.mark.parametrize(
    "exc",
    [BodyTooLarge(10), ConcurrencyLimitExceeded(5), RateLimitExceeded(3)],
)
def test_limit_errors_expose_only_safe_text(exc: BodyTooLarge) -> None:
    """Limit messages contain no stack-trace or prompt text, only the limit facts.

    Validates: R-11.4 (error names the limit, no raw exception text).
    """
    assert "Traceback" not in exc.message
    assert exc.details is not None
    assert "limit" in exc.details
