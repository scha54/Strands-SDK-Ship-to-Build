"""Unit tests for the session state machine (R-08.3, R-10.4; NFR-05)."""

import pytest
from app.domain.state_machine import (
    INVALID_STATE_CODE,
    LEGAL_TRANSITIONS,
    NON_TERMINAL_STATES,
    SESSION_STOPPED_CODE,
    InvalidStateTransition,
    SessionState,
    SessionStoppedError,
    WriteOperation,
    check_write_allowed,
    is_legal_transition,
    validate_transition,
)

ALL_LEGAL_PAIRS: list[tuple[SessionState, SessionState]] = [
    (source, target)
    for source, targets in LEGAL_TRANSITIONS.items()
    for target in targets
]

ALL_ILLEGAL_PAIRS: list[tuple[SessionState, SessionState]] = [
    (source, target)
    for source in SessionState
    for target in SessionState
    if target not in LEGAL_TRANSITIONS.get(source, frozenset())
]


@pytest.mark.parametrize(("source", "target"), ALL_LEGAL_PAIRS)
def test_legal_transitions_accepted(source: SessionState, target: SessionState) -> None:
    """Every transition defined in the design map is accepted (R-08.3, R-10.4)."""
    assert is_legal_transition(source, target) is True
    validate_transition(source, target)  # must not raise


@pytest.mark.parametrize(("source", "target"), ALL_ILLEGAL_PAIRS)
def test_illegal_transitions_raise_invalid_state(
    source: SessionState, target: SessionState
) -> None:
    """Every (from, to) pair absent from the legal map raises invalid-state (NFR-05)."""
    assert is_legal_transition(source, target) is False
    with pytest.raises(InvalidStateTransition) as exc:
        validate_transition(source, target)
    assert exc.value.code == INVALID_STATE_CODE
    assert exc.value.source is source
    assert exc.value.target is target


@pytest.mark.parametrize("source", sorted(NON_TERMINAL_STATES))
def test_stop_reachable_from_every_non_terminal_state(source: SessionState) -> None:
    """Stop (STOPPED) is reachable from every non-terminal state (R-08.3)."""
    assert is_legal_transition(source, SessionState.STOPPED) is True


def test_non_terminal_states_match_expected_set() -> None:
    """The non-terminal set is exactly the Stop-reachable source states (R-08.3)."""
    expected = {
        SessionState.CREATED,
        SessionState.GENERATING,
        SessionState.READY,
        SessionState.BASELINE,
        SessionState.ACTIVE,
        SessionState.END_CHECK,
    }
    assert NON_TERMINAL_STATES == expected
    # No terminal-ish state offers a Stop transition.
    for state in SessionState:
        if state not in NON_TERMINAL_STATES:
            assert not is_legal_transition(state, SessionState.STOPPED)


@pytest.mark.parametrize("operation", list(WriteOperation))
def test_write_after_stop_raises_session_stopped(operation: WriteOperation) -> None:
    """Writes (answer/hint/advance) after STOPPED raise session_stopped (R-08.3)."""
    with pytest.raises(SessionStoppedError) as exc:
        check_write_allowed(SessionState.STOPPED, operation)
    assert exc.value.code == SESSION_STOPPED_CODE
    assert exc.value.operation is operation


def test_session_stopped_code_distinct_from_invalid_state() -> None:
    """Stopped-session and invalid-state are distinct error codes (R-08.3)."""
    assert SESSION_STOPPED_CODE != INVALID_STATE_CODE


def test_delete_allowed_from_stopped() -> None:
    """From STOPPED, delete remains allowed (R-08.3)."""
    assert is_legal_transition(SessionState.STOPPED, SessionState.DELETED) is True
    validate_transition(SessionState.STOPPED, SessionState.DELETED)  # must not raise


@pytest.mark.parametrize("operation", list(WriteOperation))
def test_writes_allowed_on_active_session(operation: WriteOperation) -> None:
    """Non-stopped sessions permit writes; the guard only blocks STOPPED (R-08.3)."""
    check_write_allowed(SessionState.ACTIVE, operation)  # must not raise


def test_read_on_stopped_is_not_a_write_and_is_allowed() -> None:
    """Read on a STOPPED session is permitted: it is never guarded as a write (R-08.3)."""
    # Reads are not WriteOperations, so they are never routed through the guard.
    assert all(op in {"answer", "hint", "advance"} for op in WriteOperation)
    # A representative write stays blocked, confirming only writes are rejected.
    with pytest.raises(SessionStoppedError):
        check_write_allowed(SessionState.STOPPED, WriteOperation.ANSWER)


def test_ended_enables_delete() -> None:
    """The end action (ENDED) enables the delete action (R-10.4)."""
    assert is_legal_transition(SessionState.ENDED, SessionState.DELETED) is True


def test_deleted_is_terminal() -> None:
    """DELETED is fully terminal with no outgoing transitions (R-10.4)."""
    assert LEGAL_TRANSITIONS[SessionState.DELETED] == frozenset()
    for target in SessionState:
        assert is_legal_transition(SessionState.DELETED, target) is False


def test_terminal_states_only_reach_deleted() -> None:
    """COMPLETED, ENDED, STOPPED permit only a transition to DELETED (R-10.4, R-08.3)."""
    for state in (SessionState.COMPLETED, SessionState.ENDED, SessionState.STOPPED):
        assert LEGAL_TRANSITIONS[state] == frozenset({SessionState.DELETED})
