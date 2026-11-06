"""Sanitized Stage_Event emitter (R-04.5, R-12.3, NFR-05).

Events carry only ``stage``, ``specialist``, ``status``, optional
``contract_version`` and ``timestamp``. Free-form text is rejected, so prompts,
reasoning, credentials and internal IDs cannot be attached to an event.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from app.domain.models import AgentStageEvent

_SLUG = re.compile(r"^[a-z][a-z_]{0,39}$")
_VERSION = re.compile(r"^v?\d{1,3}(\.\d{1,3}){0,2}$")


class StageEmitter(Protocol):
    def __call__(
        self,
        stage: str,
        specialist: str,
        status: Literal["started", "completed", "failed"],
        contract_version: str | None = None,
    ) -> AgentStageEvent: ...


class StageEventLog:
    """In-memory, append-only log; events are readable immediately after emit."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._events: list[AgentStageEvent] = []

    @property
    def events(self) -> list[AgentStageEvent]:
        return list(self._events)

    def __call__(
        self,
        stage: str,
        specialist: str,
        status: Literal["started", "completed", "failed"],
        contract_version: str | None = None,
    ) -> AgentStageEvent:
        if not _SLUG.fullmatch(stage):
            raise ValueError("stage must be a short lowercase identifier")
        if not _SLUG.fullmatch(specialist):
            raise ValueError("specialist must be a short lowercase identifier")
        if contract_version is not None and not _VERSION.fullmatch(contract_version):
            raise ValueError("contract_version must look like 'v1' or '1.0.0'")
        event = AgentStageEvent(
            stage=stage,
            specialist=specialist,
            status=status,
            contract_version=contract_version,
            timestamp=self._clock(),
        )
        self._events.append(event)
        return event
