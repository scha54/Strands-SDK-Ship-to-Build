"""Liveness and readiness endpoints (R-11.5, R-11.6; NFR-05).

* ``GET /healthz`` is pure liveness: it makes NO external calls and returns 200 quickly
  (within 500 ms, R-11.5) even when the Session_Store or other dependencies are down. It
  only confirms the process is up and the event loop is responsive.
* ``GET /readyz`` is readiness: it probes each required dependency and returns 200 within
  2 s only when all are available (R-11.6). If any probe fails or reports unavailable, it
  returns 503 with a body naming the unavailable dependency, never a raw exception.

Readiness probes are injected via ``app.state.readiness_probes`` so tests can simulate a
down dependency without touching real AWS or the network. A probe is a callable returning
``True`` when its dependency is available; raising or returning ``False`` marks it
unavailable. Probes must be cheap and must not perform real writes (the design's readiness
check probes dependency health, not store mutations).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from fastapi import APIRouter, Request, Response

from app.api.errors import (
    CORRELATION_ID_HEADER,
    DependencyUnavailable,
    correlation_id_of,
)

# A readiness probe reports whether one dependency is available.
ReadinessProbe = Callable[[], bool]
# The injected set of probes keyed by dependency name (e.g. {"session_store": probe}).
ReadinessProbes = Mapping[str, ReadinessProbe]

# Attribute on app.state holding the injected probe map; empty means "nothing required".
READINESS_PROBES_STATE_ATTR = "readiness_probes"

router = APIRouter(tags=["health"])


def _probes_of(request: Request) -> ReadinessProbes:
    """Return the readiness probe map injected on ``app.state`` (empty if none)."""
    probes = getattr(request.app.state, READINESS_PROBES_STATE_ATTR, None)
    if isinstance(probes, Mapping):
        return probes
    return {}


@router.get("/healthz")
async def healthz(request: Request, response: Response) -> dict[str, str]:
    """Liveness check: no external calls, fast success even when dependencies are down.

    Returns 200 with ``{"status": "ok"}`` and the correlation header. It never inspects the
    Session_Store or any dependency, so it stays 200 when the store is down (R-11.5).
    """
    response.headers[CORRELATION_ID_HEADER] = correlation_id_of(request)
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, str]:
    """Readiness check: 200 only when every required dependency is available (R-11.6).

    Runs each injected probe. A probe that returns ``False`` or raises marks its dependency
    unavailable; if any are unavailable the endpoint raises :class:`DependencyUnavailable`,
    which the error handler renders as 503 naming the dependency. No raw exception text from
    a probe is exposed — only the dependency name.
    """
    unavailable: list[str] = []
    for name, probe in _probes_of(request).items():
        try:
            available = probe()
        except Exception:  # noqa: BLE001 - a failing probe means the dependency is down
            available = False
        if not available:
            unavailable.append(name)

    if unavailable:
        raise DependencyUnavailable(sorted(unavailable))

    response.headers[CORRELATION_ID_HEADER] = correlation_id_of(request)
    return {"status": "ready"}
