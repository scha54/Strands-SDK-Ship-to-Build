"""Session routes: create, read, stop, end and delete (R-01, R-08.3, R-10; NFR-01/02/08).

All routes are mounted under the ``/api/v1`` prefix (design section 6). Creation is public; every
other route is session-specific and requires ``Authorization: Bearer <capability token>`` via the
:func:`~app.api.auth.require_session` dependency, which also loads the Session (404/410 on
absent/expired) before the handler runs.

* ``POST /sessions`` — validate (``extra="forbid"`` rejects child identity fields with a 422 that
  lists every invalid field), normalize objects, create the Session and return its ``session_id``
  and the one-time ``capability_token``. No model/Bedrock call is made and no partial record is
  written on failure (R-01.3, R-01.4, R-01.6).
* ``GET /sessions/{id}`` — return the authenticated Session's sanitized state.
* ``POST /sessions/{id}/stop`` — transition to ``STOPPED`` so later answer/hint/advance writes are
  rejected (409 ``session_stopped``) while the data stays readable for review and delete (R-08.3).
* ``POST /sessions/{id}/end`` — normal end (``ENDED``), enabling delete (R-10.4).
* ``DELETE /sessions/{id}`` — permanent delete (R-10.5); a later read or delete returns 404
  (R-10.6).

Handlers return typed response models (never the raw ``SessionRecord``) so the token hash and
other internal attributes are never serialized to a client.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.auth import AuthenticatedSession, get_session_service
from app.domain.models import (
    ActivityStatus,
    AgeBand,
    CreateSessionRequest,
    ObjectItem,
    Subject,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/api/v1", tags=["sessions"])


class CreateSessionResponse(BaseModel):
    """Returned once on creation; carries the plaintext Capability_Token (R-01.2).

    The token is shown exactly once and never persisted in plaintext (only its hash is stored).
    """

    session_id: str = Field(min_length=1)
    capability_token: str = Field(min_length=1)
    state: str
    expires_at: str


class SessionView(BaseModel):
    """Sanitized Session view returned to an authenticated caller.

    Deliberately excludes ``token_hash`` and any operational secret. The learner-facing projection
    of lesson/answers is handled by a later task; this view exposes only lifecycle and setup fields.
    """

    session_id: str
    state: str
    age_band: AgeBand
    subject: Subject
    language: str
    objects: list[ObjectItem]
    activity_status: list[ActivityStatus]
    current_index: int
    created_at: str
    updated_at: str
    expires_at: str


def _view(record_session_id: str, service: SessionService) -> SessionView:
    """Build a :class:`SessionView` by reading the current record (post-transition freshness)."""
    record = service.get(record_session_id)
    return SessionView(
        session_id=record.session_id,
        state=record.state,
        age_band=record.age_band,
        subject=record.subject,
        language=record.language,
        objects=record.objects,
        activity_status=record.activity_status,
        current_index=record.current_index,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        expires_at=record.expires_at.isoformat(),
    )


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> CreateSessionResponse:
    """Create a Session and return its ID and one-time Capability_Token (R-01).

    Pydantic validates the body first: unknown identity fields (name, birthday, address, school,
    email) and out-of-bounds values fail with a 422 listing every invalid field (R-01.3, R-01.4).
    The service normalizes objects and persists exactly one record storing only the token hash; a
    normalization failure writes nothing (R-01.6). No model call occurs on this path (R-01.6).
    """
    created = service.create(request)
    return CreateSessionResponse(
        session_id=created.session_id,
        capability_token=created.capability_token,
        state=created.record.state,
        expires_at=created.record.expires_at.isoformat(),
    )


@router.get("/sessions/{session_id}")
def get_session(
    session: AuthenticatedSession,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionView:
    """Return the authenticated Session's sanitized state (R-05, R-10).

    The ``require_session`` dependency has already loaded and authorized the Session, so an absent
    (404) or expired (410) Session is rejected before this handler runs.
    """
    return _view(session.session_id, service)


@router.post("/sessions/{session_id}/stop")
def stop_session(
    session: AuthenticatedSession,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionView:
    """Stop the Session, blocking later answer/hint/advance writes (R-08.3).

    Transitions to ``STOPPED`` (idempotent). Data remains readable for review and delete; only
    write operations are rejected afterward with 409 ``session_stopped``.
    """
    service.stop(session.session_id)
    return _view(session.session_id, service)


@router.post("/sessions/{session_id}/end")
def end_session(
    session: AuthenticatedSession,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionView:
    """End the Session normally (``ENDED``), enabling delete (R-10.4)."""
    service.end(session.session_id)
    return _view(session.session_id, service)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session: AuthenticatedSession,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> None:
    """Permanently delete the Session (R-10.5).

    Returns 204 on success. A subsequent read or delete returns 404 (R-10.6) because the record is
    gone. The ``require_session`` dependency has already confirmed the Session exists and the token
    is valid, so a delete without a valid token is a 401 and never removes anything.
    """
    service.delete(session.session_id)
