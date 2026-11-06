"""Per-request budget for orchestration (R-04.4, R-04.7, NFR-07).

A single ``RequestBudget`` is shared by all specialist invocations of one request.
Every invocation first calls :meth:`RequestBudget.consume`, which raises
:class:`LimitReached` naming the exhausted limit.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal

from app.config import Settings

LimitName = Literal["depth", "calls", "tokens", "deadline"]


class LimitReached(Exception):  # noqa: N818 - name fixed by the design
    """Raised when a request exceeds one of its limits."""

    def __init__(self, limit_name: LimitName) -> None:
        super().__init__(f"limit reached: {limit_name}")
        self.limit_name: LimitName = limit_name


class RequestBudget:
    """Tracks depth, specialist calls, tokens and a deadline for one request."""

    def __init__(
        self,
        *,
        max_depth: int,
        max_calls: int,
        max_tokens: int,
        deadline_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_depth = max_depth
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.deadline_seconds = deadline_seconds
        self._clock = clock
        self._deadline_at = clock() + deadline_seconds
        self.calls = 0
        self.tokens = 0

    @classmethod
    def for_generation(
        cls, settings: Settings, clock: Callable[[], float] = time.monotonic
    ) -> RequestBudget:
        return cls._from_settings(settings, settings.generation_deadline_seconds, clock)

    @classmethod
    def for_assessment(
        cls, settings: Settings, clock: Callable[[], float] = time.monotonic
    ) -> RequestBudget:
        return cls._from_settings(settings, settings.assessment_deadline_seconds, clock)

    @classmethod
    def _from_settings(
        cls, settings: Settings, deadline_seconds: float, clock: Callable[[], float]
    ) -> RequestBudget:
        return cls(
            max_depth=settings.max_orchestration_depth,
            max_calls=settings.max_specialist_calls,
            max_tokens=settings.max_tokens_per_request,
            deadline_seconds=deadline_seconds,
            clock=clock,
        )

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline_at - self._clock())

    def consume(self, *, depth: int = 1, tokens: int = 0) -> None:
        """Account for one specialist invocation or raise ``LimitReached``.

        ``depth`` is the orchestration depth of the call (1 = orchestrator to
        specialist). ``tokens`` is the amount used so far by this invocation.
        Nothing is recorded when a limit is raised.
        """
        if self._clock() >= self._deadline_at:
            raise LimitReached("deadline")
        if depth > self.max_depth:
            raise LimitReached("depth")
        if self.calls + 1 > self.max_calls:
            raise LimitReached("calls")
        if self.tokens + tokens > self.max_tokens:
            raise LimitReached("tokens")
        self.calls += 1
        self.tokens += tokens

    def add_tokens(self, tokens: int) -> None:
        """Record tokens reported after a call completes."""
        if self.tokens + tokens > self.max_tokens:
            self.tokens = self.max_tokens
            raise LimitReached("tokens")
        self.tokens += tokens
