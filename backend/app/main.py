"""Application factory. Routes and middleware are wired in later tasks."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app with injected settings."""
    app = FastAPI(title="The Invisible Classroom", version="0.1.0")
    app.state.settings = settings or get_settings()
    return app
