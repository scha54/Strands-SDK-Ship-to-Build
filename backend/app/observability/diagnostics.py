"""Redacted per-request diagnostics, OpenTelemetry spans and metrics (R-10.3, R-11.3).

Every request produces one :class:`DiagnosticRecord`. The record's shape is closed: a
redacted correlation ID, per-stage statuses, latency in milliseconds, an error category
(from a fixed vocabulary) and an optional usage estimate. There is no free-text field, so
credentials, personal data and learner answers cannot be attached (NFR-08, NFR-01):

* the correlation ID is replaced by a truncated SHA-256 digest before it is stored;
* stage and operation names must be short lowercase identifiers;
* errors are reduced to a category; the exception message is never read.

The same safe fields feed OpenTelemetry spans and metrics: a latency histogram (p50 and
p95 are derived from it by the backend, and also available in-process through
:meth:`DiagnosticRecorder.latency_percentile`), a request counter and estimated cost per
Session.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Literal

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Status, StatusCode, Tracer
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.session_store import Expired, NotFound
from app.agents.budget import LimitReached

LOGGER_NAME = "app.diagnostics"
_LOG = logging.getLogger(LOGGER_NAME)

_SLUG = re.compile(r"^[a-z][a-z_]{0,39}$")
_DIGEST_CHARS = 16
_MAX_SAMPLES = 1000

StageStatus = Literal["started", "completed", "failed"]
ErrorCategory = Literal[
    "validation", "not_found", "expired", "limit_reached", "timeout", "dependency", "internal"
]


def redact_correlation_id(raw: str) -> str:
    """Return a stable, non-reversible token for ``raw`` (R-11.3).

    Callers can match records to a response header without the raw value (which may be
    client-supplied) ever being stored.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def categorize_error(exc: BaseException) -> ErrorCategory:
    """Map an exception to a fixed category using its type only, never its message."""
    if isinstance(exc, NotFound):
        return "not_found"
    if isinstance(exc, Expired):
        return "expired"
    if isinstance(exc, LimitReached):
        return "limit_reached"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):
        return "validation"
    if isinstance(exc, ConnectionError | OSError):
        return "dependency"
    return "internal"


class UsageEstimate(BaseModel):
    """Token count and estimated cost for one request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)


class DiagnosticRecord(BaseModel):
    """The only shape a per-request diagnostic may take (R-11.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    operation: str = Field(pattern=_SLUG.pattern)
    stage_statuses: dict[str, StageStatus]
    latency_ms: float = Field(ge=0)
    error_category: ErrorCategory | None = None
    usage_estimate: UsageEstimate | None = None


class RequestDiagnostics:
    """Mutable collector handed to the code handling one request."""

    def __init__(self) -> None:
        self.stage_statuses: dict[str, StageStatus] = {}
        self.tokens = 0

    def stage(self, name: str, status: StageStatus) -> None:
        """Record the latest status of an agent stage."""
        if not _SLUG.fullmatch(name):
            raise ValueError("stage must be a short lowercase identifier")
        self.stage_statuses[name] = status

    def add_tokens(self, tokens: int) -> None:
        """Add model tokens used by this request."""
        if tokens < 0:
            raise ValueError("tokens must not be negative")
        self.tokens += tokens


class DiagnosticRecorder:
    """Builds, logs and exports one redacted record per request."""

    def __init__(
        self,
        *,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
        clock: Callable[[], float] = time.monotonic,
        cost_per_1k_tokens_usd: float = 0.0,
    ) -> None:
        self._tracer = tracer or trace.get_tracer("app.observability")
        meter = meter or metrics.get_meter("app.observability")
        self._clock = clock
        self._cost_per_1k = cost_per_1k_tokens_usd
        self._latencies: deque[float] = deque(maxlen=_MAX_SAMPLES)
        self._session_cost: dict[str, float] = {}
        self._latency_hist = meter.create_histogram(
            "ic.request.latency", unit="ms", description="Request latency"
        )
        self._requests = meter.create_counter("ic.requests", description="Requests handled")
        self._cost = meter.create_counter(
            "ic.estimated_cost", unit="USD", description="Estimated model cost"
        )
        self._session_cost_hist = meter.create_histogram(
            "ic.session.estimated_cost", unit="USD", description="Estimated cost per Session"
        )

    @contextmanager
    def request(
        self, correlation_id: str, operation: str, *, session_key: str | None = None
    ) -> Iterator[RequestDiagnostics]:
        """Time one request and emit its record on exit, re-raising any error.

        ``session_key`` is only used to total cost per Session in memory; it is never
        logged or attached to a span or metric.
        """
        if not _SLUG.fullmatch(operation):
            raise ValueError("operation must be a short lowercase identifier")
        diag = RequestDiagnostics()
        redacted = redact_correlation_id(correlation_id)
        started = self._clock()
        category: ErrorCategory | None = None
        with self._tracer.start_as_current_span(
            f"request.{operation}",
            attributes={"ic.correlation_id": redacted, "ic.operation": operation},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield diag
            except BaseException as exc:
                category = categorize_error(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                latency_ms = max(0.0, (self._clock() - started) * 1000.0)
                record = self._build(redacted, operation, diag, latency_ms, category)
                self._export(record, session_key, span)

    def latency_percentile(self, percentile: float) -> float | None:
        """Nearest-rank percentile (0-100) of recent request latencies, or None if none."""
        if not self._latencies:
            return None
        ordered = sorted(self._latencies)
        rank = max(1, -(-len(ordered) * percentile // 100))
        return ordered[min(int(rank), len(ordered)) - 1]

    def finish_session(self, session_key: str) -> float:
        """Emit and clear the estimated cost accumulated for a Session."""
        total = self._session_cost.pop(session_key, 0.0)
        self._session_cost_hist.record(total)
        return total

    def _build(
        self,
        redacted: str,
        operation: str,
        diag: RequestDiagnostics,
        latency_ms: float,
        category: ErrorCategory | None,
    ) -> DiagnosticRecord:
        usage = None
        if diag.tokens:
            usage = UsageEstimate(
                tokens=diag.tokens, estimated_cost_usd=diag.tokens / 1000 * self._cost_per_1k
            )
        return DiagnosticRecord(
            correlation_id=redacted,
            operation=operation,
            stage_statuses=dict(diag.stage_statuses),
            latency_ms=latency_ms,
            error_category=category,
            usage_estimate=usage,
        )

    def _export(self, record: DiagnosticRecord, session_key: str | None, span: trace.Span) -> None:
        span.set_attribute("ic.latency_ms", record.latency_ms)
        for stage, status in record.stage_statuses.items():
            span.set_attribute(f"ic.stage.{stage}", status)
        if record.error_category:
            span.set_attribute("ic.error_category", record.error_category)
        attrs = {
            "ic.operation": record.operation,
            "ic.error_category": record.error_category or "none",
        }
        self._latencies.append(record.latency_ms)
        self._latency_hist.record(record.latency_ms, attrs)
        self._requests.add(1, attrs)
        if record.usage_estimate:
            span.set_attribute("ic.tokens", record.usage_estimate.tokens)
            cost = record.usage_estimate.estimated_cost_usd
            self._cost.add(cost, {"ic.operation": record.operation})
            if session_key is not None:
                self._session_cost[session_key] = self._session_cost.get(session_key, 0.0) + cost
        _LOG.info(record.model_dump_json())


__all__ = [
    "LOGGER_NAME",
    "DiagnosticRecord",
    "DiagnosticRecorder",
    "ErrorCategory",
    "RequestDiagnostics",
    "StageStatus",
    "UsageEstimate",
    "categorize_error",
    "redact_correlation_id",
]
