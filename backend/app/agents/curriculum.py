"""Curriculum_Specialist: objective and progression (R-04.1, R-04.3)."""

from __future__ import annotations

from typing import ClassVar

from app.agents.budget import RequestBudget
from app.agents.specialist import Specialist
from app.domain.models import AgeBand, CurriculumPlan, ObjectInventory, Subject


class CurriculumSpecialist(Specialist[CurriculumPlan]):
    name: ClassVar[str] = "curriculum"
    task: ClassVar[str] = (
        "Choose one learning objective and a progression of up to three steps for the "
        "age band and subject. Return the CurriculumPlan contract."
    )
    output_type = CurriculumPlan

    async def run(
        self,
        inventory: ObjectInventory,
        age_band: AgeBand,
        subject: Subject,
        budget: RequestBudget,
    ) -> CurriculumPlan:
        data = {
            "age_band": age_band.value,
            "subject": subject.value,
            "objects": [i.original for i in inventory.items if not i.excluded_reason],
        }
        return await self._run(data, budget)
