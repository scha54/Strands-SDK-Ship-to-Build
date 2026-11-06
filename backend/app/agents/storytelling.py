"""Storytelling_Specialist: story setup and three Activities (R-04.1, R-04.3)."""

from __future__ import annotations

from typing import ClassVar

from app.agents.budget import RequestBudget
from app.agents.specialist import Specialist
from app.domain.models import CurriculumPlan, ObjectInventory, StoryDraft


class StorytellingSpecialist(Specialist[StoryDraft]):
    name: ClassVar[str] = "storytelling"
    task: ClassVar[str] = (
        "Write a short story setup and exactly three Activities for the objective, using "
        "only the listed objects. Return the StoryDraft contract."
    )
    output_type = StoryDraft

    async def run(
        self, inventory: ObjectInventory, plan: CurriculumPlan, budget: RequestBudget
    ) -> StoryDraft:
        data = {
            "objects": [i.original for i in inventory.items if not i.excluded_reason],
            "objective": plan.objective,
            "age_band": plan.age_band.value,
            "subject": plan.subject.value,
            "progression": plan.progression,
        }
        return await self._run(data, budget)
