"""API tests for session service, capability auth and session routes (task 2.11).

Covered requirements:
* R-01.2 — creation returns an opaque, input-independent Session_ID and a one-time token.
* R-01.3 — invalid fields produce a 422 that lists every invalid field with no model call.
* R-01.4 — child identity fields (name, birthday, address, school, email) are rejected.
* R-01.6 — a failed creation leaves no record and makes no model call (no partial Session).
* R-08.3 — Stop blocks later answer/hint/advance writes (409 ``session_stopped``) while data
  stays readable for review and delete.
* R-10.4 — End enables delete.
* R-10.5 — Delete permanently removes the Session.
* R-10.6 — a read or delete after delete returns 404.
* R-10.8 — a read after expiry returns 410.
* NFR-01 — only the capability-token hash is stored; comparison is constant-time.
* NFR-02 — typed inputs with enforced bounds; sanitized responses omit the token hash.
* NFR-08 — explicit delete plus TTL expiry; no forbidden attributes persisted.

A deterministic clock and injected id/token generators make Session_IDs, tokens and expiry
reproducible. The capability token is never persisted in plaintext (the store holds only its
SHA-256 hash), which these tests assert directly against the in-memory store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.adapters.session_store import InMemorySessionStore, NotFound
from app.config import Settings
from app.main import create_app
from app.services.session_service import SessionService, hash_token
from fastapi.testclient import TestClient

BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
TTL = timedelta(hours=24)

VALID_BODY = {
    "age_band": "6-8",
    "subject": "arithmetic_counting",
    "objects": ["Stone", "stone", "  leaf  ", "Bottle"],
}


class FakeClock:
    """Advanceable clock so expiry (R-10.8) is deterministic in tests."""

    def __init__(self, start: datetime = BASE_TIME) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class SequentialIds:
    """Deterministic, input-independent id/token generator (R-01.2)."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._n = 0

    def __call__(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n}"


def build_client(
    clock: FakeClock | None = None,
) -> tuple[TestClient, InMemorySessionStore, FakeClock]:
    """Build a TestClient over an in-memory store with deterministic clock and generators.

    Returns the client, the underlying store (for white-box assertions on what is persisted)
    and the clock (to advance time for expiry tests).
    """
    the_clock = clock or FakeClock()
    store = InMemorySessionStore(ttl=TTL)
    service = SessionService(
        store,
        clock=the_clock,
        ttl=TTL,
        id_generator=SequentialIds("sess"),
        token_generator=SequentialIds("tok"),
    )
    app = create_app(Settings(), session_service=service)
    return TestClient(app), store, the_clock


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Creation -------------------------------------------------------------------------------


def test_valid_creation_returns_id_and_token_and_stores_only_hash() -> None:
    """Valid creation returns an opaque ID + one-time token; store holds only the hash.

    Validates: R-01.2, NFR-01, NFR-08.
    """
    client, store, _ = build_client()

    resp = client.post("/api/v1/sessions", json=VALID_BODY)

    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert body["capability_token"] == "tok-1"  # noqa: S105 - deterministic test token
    assert body["state"] == "created"

    # The store persists only the token hash, never the plaintext token (R-10.1, NFR-01).
    record = store.get("sess-1", BASE_TIME)
    assert record.token_hash == hash_token("tok-1")
    assert "tok-1" not in record.model_dump_json()
    # Objects are normalized and deduped (case-insensitive): Stone/stone collapse to one.
    normalized = [o.normalized for o in record.objects]
    assert normalized == ["stone", "leaf", "bottle"]


def test_session_id_is_input_independent() -> None:
    """Two creations with identical input get different IDs. Validates: R-01.2."""
    client, _, _ = build_client()

    first = client.post("/api/v1/sessions", json=VALID_BODY).json()["session_id"]
    second = client.post("/api/v1/sessions", json=VALID_BODY).json()["session_id"]

    assert first != second


@pytest.mark.parametrize(
    ("field", "body"),
    [
        ("age_band", {**VALID_BODY, "age_band": "99-100"}),
        ("subject", {**VALID_BODY, "subject": "astrophysics"}),
        ("objects", {**VALID_BODY, "objects": []}),
        ("objects_too_many", {**VALID_BODY, "objects": [f"o{i}" for i in range(21)]}),
        ("language", {**VALID_BODY, "language": "fr"}),
    ],
)
def test_each_invalid_field_returns_422(field: str, body: dict[str, object]) -> None:
    """Each invalid field yields a 422 with no stored record. Validates: R-01.3, R-01.6."""
    client, store, _ = build_client()

    resp = client.post("/api/v1/sessions", json=body)

    assert resp.status_code == 422, field
    assert resp.json()["code"] == "validation_error"
    # No partial Session: a fresh store has nothing under the id the service would have minted.
    with pytest.raises(NotFound):
        store.get("sess-1", BASE_TIME)


def test_422_lists_every_invalid_field() -> None:
    """A body with several invalid fields lists all of them. Validates: R-01.3."""
    client, _, _ = build_client()

    resp = client.post(
        "/api/v1/sessions",
        json={"age_band": "bad", "subject": "bad", "objects": []},
    )

    assert resp.status_code == 422
    fields = {d["field"] for d in resp.json()["details"]}
    assert any("age_band" in f for f in fields)
    assert any("subject" in f for f in fields)
    assert any("objects" in f for f in fields)


@pytest.mark.parametrize(
    "identity_field",
    ["name", "birthday", "address", "school", "email"],
)
def test_extra_identity_fields_are_rejected(identity_field: str) -> None:
    """Child identity fields fail validation with no record. Validates: R-01.4, R-01.6."""
    client, store, _ = build_client()

    resp = client.post(
        "/api/v1/sessions",
        json={**VALID_BODY, identity_field: "value"},
    )

    assert resp.status_code == 422
    fields = {d["field"] for d in resp.json()["details"]}
    assert any(identity_field in f for f in fields)
    with pytest.raises(NotFound):  # no partial Session persisted
        store.get("sess-1", BASE_TIME)


def test_failed_creation_via_http_leaves_no_record() -> None:
    """An over-long object name fails validation with nothing persisted. Validates: R-01.6."""
    client, store, _ = build_client()

    over_long = "x" * 51
    resp = client.post("/api/v1/sessions", json={**VALID_BODY, "objects": [over_long]})

    assert resp.status_code == 422
    with pytest.raises(NotFound):
        store.get("sess-1", BASE_TIME)


def test_failed_creation_at_service_level_writes_nothing() -> None:
    """When normalization fails, the service never touches the store. Validates: R-01.6.

    Exercised at the service layer so the "normalize before any write" ordering is verified
    independently of the route's Pydantic pre-validation: a spy store records every call, and
    a request whose objects collapse to zero valid names must raise before ``create`` runs.
    """
    from app.domain.models import AgeBand, CreateSessionRequest, SessionRecord, Subject
    from app.services.normalizer import NormalizationError

    class SpyStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__(ttl=TTL)
            self.create_calls = 0

        def create(self, s: SessionRecord) -> None:
            self.create_calls += 1
            raise AssertionError("store.create must not run when normalization fails")

    spy = SpyStore()
    service = SessionService(
        spy,
        clock=FakeClock(),
        ttl=TTL,
        id_generator=SequentialIds("sess"),
        token_generator=SequentialIds("tok"),
    )
    # Build the request bypassing the route so it reaches the normalizer; whitespace-only
    # names dedupe/strip to nothing and the normalizer raises TOO_FEW_OBJECTS.
    request = CreateSessionRequest.model_construct(
        age_band=AgeBand.B6_8,
        subject=Subject.ARITHMETIC,
        objects=["   ", "\t"],
        language="en",
    )

    with pytest.raises(NormalizationError):
        service.create(request)
    assert spy.create_calls == 0


# --- Authorization --------------------------------------------------------------------------


def test_wrong_token_is_rejected() -> None:
    """A valid session with the wrong bearer token returns 401. Validates: NFR-01."""
    client, _, _ = build_client()
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid = created["session_id"]

    resp = client.get(f"/api/v1/sessions/{sid}", headers=auth_header("not-the-token"))

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthorized"
    # The error never leaks whether the session exists or the correct token.
    assert "tok-1" not in resp.text


def test_missing_token_is_rejected() -> None:
    """A session route with no Authorization header returns 401. Validates: NFR-01."""
    client, _, _ = build_client()
    sid = client.post("/api/v1/sessions", json=VALID_BODY).json()["session_id"]

    resp = client.get(f"/api/v1/sessions/{sid}")

    assert resp.status_code == 401


def test_read_with_valid_token_returns_sanitized_view() -> None:
    """A valid token reads the session; the view omits the token hash. Validates: NFR-02."""
    client, _, _ = build_client()
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid, token = created["session_id"], created["capability_token"]

    resp = client.get(f"/api/v1/sessions/{sid}", headers=auth_header(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sid
    assert body["state"] == "created"
    assert "token_hash" not in body


# --- Stop / End / Delete lifecycle ----------------------------------------------------------


def test_stop_then_write_returns_409_stopped_session() -> None:
    """After Stop, a learner write is rejected with 409 ``session_stopped``; data stays readable.

    The answer/hint/advance routes are implemented in a later task, so the stopped-session
    rejection is verified at the state-machine guard the write path uses, and the Session is
    confirmed still readable and deletable after Stop. Validates: R-08.3, R-10.4.
    """
    from app.domain.state_machine import (
        SessionState,
        SessionStoppedError,
        WriteOperation,
        check_write_allowed,
    )

    client, _, _ = build_client()
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid, token = created["session_id"], created["capability_token"]

    stop_resp = client.post(f"/api/v1/sessions/{sid}/stop", headers=auth_header(token))
    assert stop_resp.status_code == 200
    assert stop_resp.json()["state"] == SessionState.STOPPED.value

    # The write guard the answer/hint/advance path uses rejects writes on a stopped session.
    with pytest.raises(SessionStoppedError) as excinfo:
        check_write_allowed(SessionState.STOPPED, WriteOperation.ANSWER)
    assert excinfo.value.code == "session_stopped"

    # Data remains readable for review (R-08.3) ...
    read = client.get(f"/api/v1/sessions/{sid}", headers=auth_header(token))
    assert read.status_code == 200
    # ... and deletable.
    deleted = client.delete(f"/api/v1/sessions/{sid}", headers=auth_header(token))
    assert deleted.status_code == 204


def test_end_from_created_is_illegal_409() -> None:
    """End is illegal from CREATED (ENDED is only reachable from ACTIVE). Validates: R-10.4."""
    client, _, _ = build_client()
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid, token = created["session_id"], created["capability_token"]

    resp = client.post(f"/api/v1/sessions/{sid}/end", headers=auth_header(token))

    assert resp.status_code == 409
    assert resp.json()["code"] == "invalid_state"


def test_end_from_active_then_delete() -> None:
    """From an active lesson, End enables delete; delete returns 204. Validates: R-10.4, R-10.5."""
    client, store, clock = build_client()
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid, token = created["session_id"], created["capability_token"]

    # Drive the Session to ACTIVE directly through the store (lesson generation is a later
    # task); ENDED is legal only from ACTIVE per the state machine.
    record = store.get(sid, clock.now())
    store.put_if_version(record.model_copy(update={"state": "active"}), record.version)

    end_resp = client.post(f"/api/v1/sessions/{sid}/end", headers=auth_header(token))
    assert end_resp.status_code == 200
    assert end_resp.json()["state"] == "ended"

    delete_resp = client.delete(f"/api/v1/sessions/{sid}", headers=auth_header(token))
    assert delete_resp.status_code == 204


def test_read_and_delete_after_delete_return_404() -> None:
    """Read or delete after delete is 404. Validates: R-10.6."""
    client, _, _ = build_client()
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid, token = created["session_id"], created["capability_token"]

    assert client.delete(f"/api/v1/sessions/{sid}", headers=auth_header(token)).status_code == 204

    read = client.get(f"/api/v1/sessions/{sid}", headers=auth_header(token))
    assert read.status_code == 404
    assert read.json()["code"] == "not_found"

    delete_again = client.delete(f"/api/v1/sessions/{sid}", headers=auth_header(token))
    assert delete_again.status_code == 404


def test_read_after_expiry_returns_410() -> None:
    """A read at/after expires_at is 410. Validates: R-10.8, NFR-08."""
    clock = FakeClock()
    client, _, _ = build_client(clock=clock)
    created = client.post("/api/v1/sessions", json=VALID_BODY).json()
    sid, token = created["session_id"], created["capability_token"]

    # Advance past the 24 h TTL window; the read must be rejected as expired.
    clock.advance(TTL + timedelta(seconds=1))

    resp = client.get(f"/api/v1/sessions/{sid}", headers=auth_header(token))

    assert resp.status_code == 410
    assert resp.json()["code"] == "expired"


def test_create_imports_no_model_adapter() -> None:
    """The session service imports no Bedrock/agent module, so creation makes no model call.

    Validates: R-01.6. Checked via the module's import statements (AST), not raw text, so the
    assertion is not confused by prose in docstrings that merely mentions the word.
    """
    import ast

    import app.services.session_service as svc

    assert svc.__file__ is not None
    with open(svc.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)

    forbidden = ("bedrock", "agents", "boto3", "strands")
    offenders = [m for m in imported_modules if any(f in m.lower() for f in forbidden)]
    assert offenders == [], f"session service must not import a model adapter: {offenders}"
