"""Assessment_Specialist: rubric-based judgement of an answer (R-04.1, R-04.3)."""

from __future__ import annotations

from typing import ClassVar

from app.agents.budget import RequestBudget
from app.agents.specialist import Specialist
from app.domain.models import Activity, AssessmentOutput


class AssessmentSpecialist(Specialist[AssessmentOutput]):
    name: ClassVar[str] = "assessment"
    task: ClassVar[str] = (
        "Assess the learner answer against the expected answer and rubric. Give one status, "
        "a short encouraging explanation and any misconception. Return the AssessmentOutput "
        "contract."
    )
    output_type = AssessmentOutput

    async def run(self, activity: Activity, answer: str, budget: RequestBudget) -> AssessmentOutput:
        data = {
            "instruction": activity.instruction,
            "expected_answer": activity.expected_answer,
            "rubric": activity.rubric,
            "answer_kind": activity.answer_kind,
            "answer": answer,
        }
        return await self._run(data, budget)
