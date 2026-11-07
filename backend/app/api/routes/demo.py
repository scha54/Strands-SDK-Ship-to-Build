"""Demo_Mode route: ``POST /api/v1/demo/session`` (R-12.1, R-12.2, R-12.4).

Creates the preset Session from the seed with no user input or image, returns the one-time
Capability_Token with the five pending stages, and runs the stages after the response. Progress
is read through ``GET /sessions/{id}/events``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from pydantic import BaseModel

from app.services.demo_service import DemoService, map_stages

router = APIRouter(prefix="/api/v1", tags=["demo"])


def get_demo_service(request: Request) -> DemoService:
    service = getattr(request.app.state, "demo_service", None)
    if not isinstance(service, DemoService):  # pragma: no cover - configuration guard
        raise RuntimeError("demo_service is not configured on app.state")
    return service


class DemoStageView(BaseModel):
    stage: str
    title: str
    state: str


class DemoSessionResponse(BaseModel):
    session_id: str
    capability_token: str
    state: str
    expires_at: str
    age_band: str
    subject: str
    subject_label: str
    objects: list[str]
    stages: list[DemoStageView]
    events_url: str


@router.post("/demo/session", status_code=status.HTTP_201_CREATED)
def create_demo_session(
    background: BackgroundTasks,
    service: Annotated[DemoService, Depends(get_demo_service)],
) -> DemoSessionResponse:
    created = service.create_session()
    seed = service.seed
    background.add_task(service.run, created.session_id)
    return DemoSessionResponse(
        session_id=created.session_id,
        capability_token=created.capability_token,
        state=created.record.state,
        expires_at=created.record.expires_at.isoformat(),
        age_band=seed.age_band.value,
        subject=seed.subject.value,
        subject_label=seed.subject_label,
        objects=list(seed.objects),
        stages=[DemoStageView(stage=s.stage, title=s.title, state=s.state) for s in map_stages([])],
        events_url=f"/api/v1/sessions/{created.session_id}/events",
    )
