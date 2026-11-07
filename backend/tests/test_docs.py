"""Docs check: required files exist, demo script fits 180 s, setup path runs all five stages.

Validates: Requirements R-12.5, R-12.6; NFR-06, NFR-09.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings
from app.main import create_app
from app.services.demo_seed import STAGE_ORDER, load_demo_seed
from app.services.normalizer import normalize_objects
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = [
    "README.md",
    "docs/architecture.md",
    "docs/demo-script.md",
    "docs/release-gates.md",
    "backend/app/templates/demo_seed/demo_seed.json",
]


def test_required_docs_exist_and_cover_topics() -> None:
    for rel in REQUIRED:
        assert (ROOT / rel).is_file(), rel
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for topic in ("Setup", "Seed data", "Tests", "app.evaluation", "test:e2e", "illustrative"):
        assert topic in readme, topic
    gates = (ROOT / "docs/release-gates.md").read_text(encoding="utf-8")
    for gate in ("G1", "G2", "G3", "G4", "G5"):
        assert gate in gates
    assert "measured" in gates.lower() and "illustrative" in gates.lower()
    assert "Demo fallback \u2014 no live agent execution" in gates


def test_demo_script_steps_total_at_most_180_seconds() -> None:
    text = (ROOT / "docs/demo-script.md").read_text(encoding="utf-8")
    steps = re.findall(r"^\d+\. \[[\d:]+-[\d:]+\] \((\d+) s\)", text, flags=re.MULTILINE)
    assert len(steps) >= 5
    assert 0 < sum(int(s) for s in steps) <= 180


def test_seed_preset_keeps_seven_distinct_objects() -> None:
    """R-12.1: the seed survives normalization as exactly seven Objects."""
    assert len(normalize_objects(list(load_demo_seed().objects)).items) == 7


def test_frontend_preset_mirrors_seed() -> None:
    """R-01.5, R-12.1: the form preset lists the seed's Objects verbatim (no drift)."""
    source = (ROOT / "frontend/src/features/setup/demoPreset.ts").read_text(encoding="utf-8")
    block = re.search(r"objects:\s*\[(.*?)\]", source, flags=re.DOTALL)
    assert block is not None
    assert re.findall(r'"([^"]+)"', block.group(1)) == list(load_demo_seed().objects)


def test_documented_setup_runs_demo_through_five_stages_twice() -> None:
    """R-12.6: the README path (stub model, POST /demo/session, GET events) is repeatable."""
    runs = []
    for _ in range(2):
        client = TestClient(create_app(Settings(use_stub_model=True)))
        created = client.post("/api/v1/demo/session").json()
        headers = {"Authorization": f"Bearer {created['capability_token']}"}
        view = client.get(created["events_url"], headers=headers).json()
        assert view["state"] == "ready"
        completed = [e["stage"] for e in view["events"] if e["status"] == "completed"]
        assert tuple(completed) == STAGE_ORDER
        runs.append(completed)
    assert runs[0] == runs[1]
