"""Configuration tests."""

from __future__ import annotations

import pytest
from app.config import Settings
from app.main import create_app
from hypothesis import given, settings
from hypothesis import strategies as st

DEFAULTS: dict[str, object] = {
    "max_orchestration_depth": 2,
    "max_specialist_calls": 8,
    "generation_deadline_seconds": 45.0,
    "assessment_deadline_seconds": 15.0,
    "specialist_retries": 2,
    "lesson_generation_retries": 2,
    "max_tokens_per_request": 20_000,
    "max_request_body_bytes": 1_048_576,
    "max_concurrent_requests": 50,
    "rate_limit_per_minute": 60,
    "idempotency_window_hours": 24,
    "session_ttl_hours": 24,
    "max_generations_per_session": 2,
    "demo_fallback_trigger_seconds": 10.0,
    "model_call_timeout_seconds": 15.0,
    "model_retry_backoff_seconds": 0.2,
    "circuit_breaker_failure_threshold": 5,
    "circuit_breaker_reset_seconds": 30.0,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(f"IC_{name.upper()}", raising=False)


def test_defaults_match_design() -> None:
    """Defaults equal the design limits. Validates: R-04.4, R-11.4, NFR-07."""
    s = Settings()
    for name, expected in DEFAULTS.items():
        assert getattr(s, name) == expected, name
    assert s.model_id
    assert s.aws_region


def test_every_default_covered() -> None:
    """The defaults table covers every non-model field. Validates: NFR-07."""
    assert set(DEFAULTS) == set(Settings.model_fields) - {
        "model_id",
        "aws_region",
        "use_stub_model",
    }
    assert Settings().use_stub_model is False


@pytest.mark.parametrize("name", sorted(DEFAULTS))
def test_each_limit_overridable_by_env(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each default limit is overridable by env. Validates: R-04.4, R-11.4, NFR-07."""
    default = DEFAULTS[name]
    override: int | float = default + 1 if isinstance(default, int) else default + 1.5  # type: ignore[operator]
    monkeypatch.setenv(f"IC_{name.upper()}", str(override))
    assert getattr(Settings(), name) == override


def test_model_and_region_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model ID and region come from the environment. Validates: NFR-07."""
    monkeypatch.setenv("IC_MODEL_ID", "test.model-v1")
    monkeypatch.setenv("IC_AWS_REGION", "eu-west-1")
    s = Settings()
    assert (s.model_id, s.aws_region) == ("test.model-v1", "eu-west-1")


@settings(max_examples=100, deadline=None)
@given(st.integers(min_value=1, max_value=10**9))
def test_int_override_roundtrip(value: int) -> None:
    """Feature: invisible-classroom, config override roundtrip. Validates: R-11.4, NFR-07."""
    assert Settings(max_request_body_bytes=value).max_request_body_bytes == value


def test_invalid_override_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out-of-range values are rejected. Validates: NFR-02."""
    monkeypatch.setenv("IC_MAX_CONCURRENT_REQUESTS", "0")
    with pytest.raises(ValueError):
        Settings()


def test_no_secret_fields() -> None:
    """Settings define no credential fields. Validates: NFR-01."""
    banned = ("secret", "password", "credential", "api_key", "access_key", "auth_token")
    assert not [n for n in Settings.model_fields if any(b in n for b in banned)]


def test_app_factory_uses_injected_settings() -> None:
    """The app factory accepts injected settings. Validates: NFR-07."""
    s = Settings(max_specialist_calls=3)
    assert create_app(s).state.settings.max_specialist_calls == 3
