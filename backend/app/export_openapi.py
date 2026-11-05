"""Export the FastAPI OpenAPI schema to a JSON file.

Used by the frontend type-generation npm script to produce TypeScript types
from the backend contract without needing a running server (R-04.3; NFR-02).

Routes are wired in later tasks, so the bare FastAPI app currently exposes no
component schemas. To give the frontend a real, typed contract today, this
exporter augments the OpenAPI document with the JSON Schemas of the domain
models declared in ``app.domain.models``. The schemas come straight from the
Pydantic contracts, so the generated TypeScript types stay in lock-step with
the backend.

Usage:
    python -m app.export_openapi [output_path]

Defaults to writing ``openapi.json`` in the current working directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.domain import models
from app.main import create_app

# Domain contracts surfaced to the frontend. Each becomes a named component
# schema in the exported OpenAPI document.
_EXPORTED_MODELS = (
    models.AgeBand,
    models.Subject,
    models.AssessmentStatus,
    models.CreateSessionRequest,
    models.ObjectItem,
    models.ObjectInventory,
    models.Activity,
    models.Question,
    models.Lesson,
    models.Assessment,
    models.AnswerRequest,
    models.GateResult,
    models.Grade,
    models.AgentStageEvent,
    models.SessionSummary,
    models.ApiError,
    models.EnvironmentOutput,
    models.CurriculumPlan,
    models.StoryDraft,
    models.AssessmentOutput,
)


def _domain_component_schemas() -> dict[str, Any]:
    """Build a combined JSON Schema ``$defs`` map for every exported model."""
    defs: dict[str, Any] = {}
    for model in _EXPORTED_MODELS:
        adapter = TypeAdapter(model)
        schema = adapter.json_schema(ref_template="#/components/schemas/{model}")
        # Pull nested definitions up to the top level and flatten the root.
        nested = schema.pop("$defs", {})
        defs.update(nested)
        defs[model.__name__] = schema
    return defs


def build_schema() -> dict[str, Any]:
    """Return the OpenAPI document augmented with domain component schemas."""
    app = create_app()
    schema = app.openapi()
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for name, model_schema in _domain_component_schemas().items():
        schemas.setdefault(name, model_schema)
    return schema


def export(output_path: str | Path = "openapi.json") -> Path:
    """Write the application's OpenAPI schema to ``output_path`` and return it."""
    out = Path(output_path)
    if out.parent != Path():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(build_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    target = args[0] if args else "openapi.json"
    written = export(target)
    print(f"Wrote OpenAPI schema to {written.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
