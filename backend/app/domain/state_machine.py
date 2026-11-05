"""Session state machine and legal transitions (R-08.3, R-10.4; NFR-05).

The source machine from the design is implemented here. ``STOPPED`` is added to
satisfy R-08.3: after Stop, answer/hint/advance (write) requests return a
stopped-session error, while read and delete remain allowed. ``ENDED`` enables
the delete action (R-10.4). Terminal states (``COMPLETED``, ``ENDED``,
``STOPPED``) permit only a transition to ``DELETED``; ``DELETED`` is fully
terminal with no outgoing transitions.

Exceptions carry a string ``code`` attribute so the API error layer
(``app/api/errors.py``) can map them to the response ``code`` field without
re-deriving the cause: illegal transitions map to ``invalid_state`` and writes
against a stopped session map to ``session_stopped`` (both surface as HTTP 409
with distinct codes, per the design status mapping).
"""

from __future__ import annotations

from enum import StrEnum

INVALID_STATE_CODE = "invalid_state"
SESSION_STOPPED_CODE = "session_stopped"


class SessionState(StrEnum):
    """Lifecycle states of a Session."""

    CREATED = "created"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    BASELINE = "baseline"
    ACTIVE = "active"
    END_CHECK = "end_check"
    COMPLETED = "completed"
    ENDED = "ended"
    STOPPED = "stopped"
    DELETED = "deleted"


class WriteOperation(StrEnum):
    """Learner-facing write operations rejected once a Session is stopped."""

    ANSWER = "answer"
    HINT = "hint"
    ADVANCE = "advance"


# Non-terminal states from which Stop must be reachable (R-08.3).
NON_TERMINAL_STATES: frozenset[SessionState] = frozenset(
    {
        SessionState.CREATED,
        SessionState.GENERATING,
        SessionState.READY,
        SessionState.BASELINE,
        SessionState.ACTIVE,
        SessionState.END_CHECK,
    }
)

# Legal transitions, authoritative per design.md section 5 state machine.
LEGAL_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.CREATED: frozenset({SessionState.GENERATING, SessionState.STOPPED}),
    SessionState.GENERATING: frozenset(
        {SessionState.READY, SessionState.FAILED, SessionState.STOPPED}
    ),
    SessionState.READY: frozenset({SessionState.BASELINE, SessionState.STOPPED}),
    SessionState.FAILED: frozenset({SessionState.GENERATING}),
    SessionState.BASELINE: frozenset({SessionState.ACTIVE, SessionState.STOPPED}),
    SessionState.ACTIVE: frozenset(
        {
            SessionState.ACTIVE,
            SessionState.END_CHECK,
            SessionState.ENDED,
            SessionState.STOPPED,
        }
    ),
    SessionState.END_CHECK: frozenset({SessionState.COMPLETED, SessionState.STOPPED}),
    SessionState.COMPLETED: frozenset({SessionState.DELETED}),
    SessionState.ENDED: frozenset({SessionState.DELETED}),
    SessionState.STOPPED: frozenset({SessionState.DELETED}),
    SessionState.DELETED: frozenset(),
}


class StateMachineError(Exception):
    """Base error for state machine violations; carries an API ``code``."""

    code: str

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidStateTransition(StateMachineError):
    """Raised when a (from -> to) transition is not in the legal map."""

    def __init__(self, source: SessionState, target: SessionState) -> None:
        super().__init__(
            f"illegal transition {source.value!r} -> {target.value!r}",
            code=INVALID_STATE_CODE,
        )
        self.source = source
        self.target = target


class SessionStoppedError(StateMachineError):
    """Raised when a write operation is attempted on a stopped Session (R-08.3)."""

    def __init__(self, operation: WriteOperation) -> None:
        super().__init__(
            f"session is stopped; {operation.value!r} is not allowed",
            code=SESSION_STOPPED_CODE,
        )
        self.operation = operation


def is_legal_transition(source: SessionState, target: SessionState) -> bool:
    """Return whether ``source -> target`` is a legal transition."""
    return target in LEGAL_TRANSITIONS.get(source, frozenset())


def validate_transition(source: SessionState, target: SessionState) -> None:
    """Validate a transition, raising :class:`InvalidStateTransition` if illegal."""
    if not is_legal_transition(source, target):
        raise InvalidStateTransition(source, target)


def check_write_allowed(state: SessionState, operation: WriteOperation) -> None:
    """Guard a learner write (answer/hint/advance) against a stopped Session.

    Raises :class:`SessionStoppedError` (code ``session_stopped``) when the
    Session is ``STOPPED``. Read and delete are not write operations and are
    never routed through this guard, so they remain allowed (R-08.3).
    """
    if state is SessionState.STOPPED:
        raise SessionStoppedError(operation)
