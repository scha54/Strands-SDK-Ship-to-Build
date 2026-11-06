"""Tests for redacted per-request diagnostics, spans and metrics.

Covers R-10.3 and R-11.3 (diagnostic records exclude learner free text, credentials and
personal data but carry the required fields), NFR-01 (no credentials in telemetry) and
NFR-08 (data minimization).
"""

from __future__ import annotations

import json
import logging

import pytest
from app.adapters.session_store import Expired
from app.agents.budget import LimitReached
from app.observability.diagnostics import (
    LOGGER_NAME,
    DiagnosticRecord,
    DiagnosticRecorder,
    categorize_error,
    redact_correlation_id,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

ANSWER = "my answer is seven apples for Jane Doe"
SECRET = "AKIAIOSFODNN7EXAMPLE-secret-token"  # noqa: S105 - test sentinel


class Rig:
    def __init__(self) -> None:
        self.spans = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(self.spans))
        self.reader = InMemoryMetricReader()
        meter_provider = MeterProvider(metric_readers=[self.reader])
        self.ticks = iter(float(i) for i in range(0, 1000, 1))
        self.recorder = DiagnosticRecorder(
            tracer=tracer_provider.get_tracer("t"),
            meter=meter_provider.get_meter("m"),
            clock=lambda: next(self.ticks) * 0.05,
            cost_per_1k_tokens_usd=2.0,
        )

    def metric_names(self) -> set[str]:
        data = self.reader.get_metrics_data()
        assert data is not None
        return {
            m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
        }


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == LOGGER_NAME]


def test_record_has_required_fields_and_no_free_text(caplog: pytest.LogCaptureFixture) -> None:
    """R-11.3: each record carries ID, stage statuses, latency, usage; R-10.3: no answer text."""
    rig = Rig()
    caplog.set_level(logging.DEBUG)
    with rig.recorder.request(f"{SECRET}", "assess") as diag:
        diag.stage("assessment", "completed")
        diag.add_tokens(500)
    (rec,) = _records(caplog)
    assert set(rec) == {
        "correlation_id",
        "operation",
        "stage_statuses",
        "latency_ms",
        "error_category",
        "usage_estimate",
    }
    assert rec["correlation_id"] == redact_correlation_id(SECRET)
    assert rec["stage_statuses"] == {"assessment": "completed"}
    assert rec["latency_ms"] == pytest.approx(50.0)
    assert rec["error_category"] is None
    assert rec["usage_estimate"] == {"tokens": 500, "estimated_cost_usd": 1.0}
    assert SECRET not in caplog.text


def test_error_message_with_answer_text_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """R-10.3, NFR-08: an exception carrying answer text yields only a category."""
    rig = Rig()
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError), rig.recorder.request("abc", "assess") as diag:
        diag.stage("assessment", "failed")
        raise ValueError(f"{ANSWER} {SECRET}")
    (rec,) = _records(caplog)
    assert rec["error_category"] == "validation"
    assert ANSWER not in caplog.text
    assert SECRET not in caplog.text
    for span in rig.spans.get_finished_spans():
        assert ANSWER not in repr(dict(span.attributes or {}))
        assert not span.events
        assert SECRET not in repr(span.status.description)


def test_spans_and_metrics_exported() -> None:
    """NFR-01, R-11.3: spans carry safe attributes; latency and cost metrics exist."""
    rig = Rig()
    with rig.recorder.request("cid", "generate", session_key="s1") as diag:
        diag.stage("environment", "completed")
        diag.add_tokens(1000)
    assert rig.recorder.finish_session("s1") == pytest.approx(2.0)
    (span,) = rig.spans.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["ic.correlation_id"] == redact_correlation_id("cid")
    assert span.attributes["ic.stage.environment"] == "completed"
    assert {"ic.request.latency", "ic.requests", "ic.estimated_cost"} <= rig.metric_names()
    assert "ic.session.estimated_cost" in rig.metric_names()


def test_latency_percentiles() -> None:
    """R-11.3: p50 and p95 latency are available."""
    rig = Rig()
    assert rig.recorder.latency_percentile(50) is None
    for _ in range(20):
        with rig.recorder.request("c", "generate"):
            pass
    assert rig.recorder.latency_percentile(50) == pytest.approx(50.0)
    assert rig.recorder.latency_percentile(95) == pytest.approx(50.0)


def test_error_categories_and_validation() -> None:
    """R-11.3: error category from type only; free-form names are rejected."""
    assert categorize_error(Expired("x")) == "expired"
    assert categorize_error(LimitReached("calls")) == "limit_reached"
    assert categorize_error(TimeoutError()) == "timeout"
    assert categorize_error(RuntimeError(ANSWER)) == "internal"
    rig = Rig()
    with pytest.raises(ValueError), rig.recorder.request("c", ANSWER):
        pass
    with pytest.raises(ValidationError):
        DiagnosticRecord.model_validate(
            {
                "correlation_id": "0123456789abcdef",
                "operation": "assess",
                "stage_statuses": {},
                "latency_ms": 1,
                "answer": ANSWER,
            }
        )
    with pytest.raises(ValidationError):
        DiagnosticRecord.model_validate(
            {
                "correlation_id": SECRET,
                "operation": "assess",
                "stage_statuses": {},
                "latency_ms": 1,
            }
        )
