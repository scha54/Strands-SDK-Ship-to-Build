"""Health endpoint tests: /healthz liveness and /readyz readiness (R-11.5, R-11.6; NFR-05).

* ``/healthz`` must return 200 quickly (within 500 ms, R-11.5) with no external calls — even
  when the store/dependencies are down. The test injects a probe that would raise if called
  and asserts the liveness path never touches it.
* ``/readyz`` must return 200 within 2 s only when all required dependencies are available
  (R-11.6); otherwise 503 with a body naming the unavailable dependency. Probes are injected
  so a down dependency is simulated without real AWS or network.
"""

from __future__ import annotations

import time

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def _boom() -> bool:
    """A probe that fails as if its dependency raised while being checked."""
    raise RuntimeError("store connection refused")


def test_healthz_returns_200_when_store_is_down() -> None:
    """Liveness stays 200 even with a failing dependency probe. Validates: R-11.5."""
    # Inject a probe that would raise if liveness touched it; /healthz must ignore it.
    app = create_app(Settings(), readiness_probes={"session_store": _boom})
    client = TestClient(app)

    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_is_fast() -> None:
    """Liveness returns well within the 500 ms budget. Validates: R-11.5."""
    app = create_app(Settings())
    client = TestClient(app)

    start = time.perf_counter()
    resp = client.get("/healthz")
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    assert elapsed < 0.5


def test_readyz_returns_200_when_all_dependencies_available() -> None:
    """Readiness is 200 when every probe reports available. Validates: R-11.6."""
    app = create_app(
        Settings(),
        readiness_probes={"session_store": lambda: True, "bedrock": lambda: True},
    )
    client = TestClient(app)

    start = time.perf_counter()
    resp = client.get("/readyz")
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
    assert elapsed < 2.0


def test_readyz_returns_200_with_no_required_dependencies() -> None:
    """With no injected probes, readiness is trivially 200. Validates: R-11.6."""
    app = create_app(Settings())
    client = TestClient(app)

    assert client.get("/readyz").status_code == 200


def test_readyz_returns_503_naming_the_unavailable_dependency() -> None:
    """A down dependency -> 503 naming it. Validates: R-11.6."""
    app = create_app(
        Settings(),
        readiness_probes={"session_store": lambda: False, "bedrock": lambda: True},
    )
    client = TestClient(app)

    resp = client.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "dependency_unavailable"
    assert "session_store" in body["message"]
    assert body["details"]["unavailable"] == ["session_store"]
    # The available dependency is not named as unavailable.
    assert "bedrock" not in body["details"]["unavailable"]


def test_readyz_treats_raising_probe_as_unavailable() -> None:
    """A probe that raises marks its dependency unavailable without leaking the error.

    Validates: R-11.6 (names the dependency, no raw exception text).
    """
    app = create_app(Settings(), readiness_probes={"session_store": _boom})
    client = TestClient(app)

    resp = client.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["details"]["unavailable"] == ["session_store"]
    assert "connection refused" not in body["message"]  # no raw exception text


def test_readyz_names_all_unavailable_dependencies_sorted() -> None:
    """Multiple down dependencies are all named, in a stable order. Validates: R-11.6."""
    app = create_app(
        Settings(),
        readiness_probes={
            "session_store": lambda: False,
            "bedrock": lambda: False,
            "config": lambda: True,
        },
    )
    client = TestClient(app)

    resp = client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["details"]["unavailable"] == ["bedrock", "session_store"]
