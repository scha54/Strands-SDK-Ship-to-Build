"""CI workflow structure test."""

from __future__ import annotations

from pathlib import Path

CI_FILE = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_ci_steps_in_required_order() -> None:
    """CI lists lint, tests, secret scan, dependency scan, SBOM, build in order.

    Validates: NFR-06, NFR-01.
    """
    text = CI_FILE.read_text(encoding="utf-8")
    markers = ["ruff check", "mypy", "pytest", "gitleaks", "pip-audit", "cyclonedx-py", "uv build"]
    positions = [text.index(m) for m in markers]
    assert positions == sorted(positions)
