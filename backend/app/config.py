"""Typed application configuration.

All values come from environment variables prefixed ``IC_`` (for example
``IC_MAX_SPECIALIST_CALLS=4``). No secrets are defined here; AWS credentials come
from the runtime IAM role (NFR-01). Model, region, limits and budgets are all
configurable (NFR-07, R-04.4, R-11.4).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with the design's default limits."""

    model_config = SettingsConfigDict(env_prefix="IC_", extra="ignore", frozen=True)

    # Model and region (NFR-07). The model ID is a configuration value, not a secret.
    model_id: str = Field(default="anthropic.claude-3-5-sonnet-20240620-v1:0", min_length=1)
    aws_region: str = Field(default="us-east-1", min_length=1)

    # Orchestration limits (R-04.4).
    max_orchestration_depth: int = Field(default=2, ge=1)
    max_specialist_calls: int = Field(default=8, ge=1)
    generation_deadline_seconds: float = Field(default=45.0, gt=0)
    assessment_deadline_seconds: float = Field(default=15.0, gt=0)
    specialist_retries: int = Field(default=2, ge=0)
    lesson_generation_retries: int = Field(default=2, ge=0)
    max_tokens_per_request: int = Field(default=20_000, ge=1)

    # Bedrock client resilience (NFR-05, NFR-07).
    model_call_timeout_seconds: float = Field(default=15.0, gt=0)
    model_retry_backoff_seconds: float = Field(default=0.2, ge=0)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_reset_seconds: float = Field(default=30.0, gt=0)
    use_stub_model: bool = False

    # Request limits (R-11.4).
    max_request_body_bytes: int = Field(default=1_048_576, ge=1)
    max_concurrent_requests: int = Field(default=50, ge=1)
    rate_limit_per_minute: int = Field(default=60, ge=1)

    # Budgets and retention (R-10, R-11.2).
    idempotency_window_hours: int = Field(default=24, ge=1)
    session_ttl_hours: int = Field(default=24, ge=1)
    max_generations_per_session: int = Field(default=2, ge=1)
    demo_fallback_trigger_seconds: float = Field(default=10.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings loaded from the environment."""
    return Settings()
