"""Environment_Specialist: object inventory and affordances (R-04.1, R-04.3)."""

from __future__ import annotations

from typing import ClassVar

from app.agents.budget import RequestBudget
from app.agents.specialist import Specialist
from app.domain.models import EnvironmentOutput


class EnvironmentSpecialist(Specialist[EnvironmentOutput]):
    name: ClassVar[str] = "environment"
    task: ClassVar[str] = (
        "Build an object inventory from the listed household objects. Mark unsafe objects "
        "with excluded_reason and a safe_alternative. Return the EnvironmentOutput contract."
    )
    output_type = EnvironmentOutput

    async def run(self, objects: list[str], budget: RequestBudget) -> EnvironmentOutput:
        return await self._run({"objects": objects}, budget)
