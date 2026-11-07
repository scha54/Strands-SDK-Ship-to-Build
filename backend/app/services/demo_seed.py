"""Demo_Mode seed loader: the seed file is the single source of truth (R-12.1, R-12.4, R-12.6).

The seed lives in ``app/templates/demo_seed/demo_seed.json``. It holds the preset (Age_Band 6-8,
mathematics mapped to ``arithmetic_counting``, exactly seven Objects), the five pre-recorded
stages in order, a scripted learner answer, the recorded assessment and the Demo_Fallback Lesson.
Nothing here is learner data; it is fixed synthetic content (NFR-09: no efficacy claims).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import AgeBand, Assessment, Lesson, Subject

SEED_PATH = Path(__file__).resolve().parent.parent / "templates" / "demo_seed" / "demo_seed.json"

DEMO_FALLBACK_LABEL = "Demo fallback — no live agent execution"

# The five sanitized stages, in display order (R-12.2).
STAGE_ORDER: tuple[str, ...] = (
    "understand_objects",
    "choose_objective",
    "create_story",
    "assess_answer",
    "adapt_next_activity",
)
STAGE_TITLES: dict[str, str] = {
    "understand_objects": "Understand objects",
    "choose_objective": "Choose objective",
    "create_story": "Create story",
    "assess_answer": "Assess answer",
    "adapt_next_activity": "Adapt next activity",
}


class SeedStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str
    specialist: str
    contract_version: str | None = None


class ScriptedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: str
    answer: str


class DemoSeed(BaseModel):
    """Typed view of the seed file."""

    model_config = ConfigDict(extra="forbid")
    version: str
    age_band: AgeBand
    subject: Subject
    subject_label: str
    objects: list[str] = Field(min_length=1, max_length=20)
    scripted_answer: ScriptedAnswer
    stages: list[SeedStage]
    assessment: Assessment
    lesson: Lesson


@lru_cache
def load_demo_seed() -> DemoSeed:
    """Load and validate the seed file (cached; the file is immutable at runtime)."""
    seed = DemoSeed.model_validate(json.loads(SEED_PATH.read_text(encoding="utf-8")))
    if tuple(s.stage for s in seed.stages) != STAGE_ORDER:
        raise ValueError("demo seed stages must follow the five-stage order")
    return seed
