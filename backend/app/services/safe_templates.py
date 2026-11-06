"""Curated Safe_Template Lessons for every Age_Band and Subject (R-03.5; NFR-10).

A Safe_Template is a pre-written Lesson used when generation fails the gates after the
allowed attempts, or when the Facilitator picks it after a model error. Activities use
pretend quantities ("Pretend you have 3 stone items") so they work with any one Object,
need no purchased supplies, and contain no hazards. The ``{obj}`` placeholder is replaced
with one usable Object from the Facilitator's inventory, so the Lesson stays grounded.

Every template carries ``source="safe_template"`` and a visible label that is the first
sentence of its ``setup`` (see :data:`SAFE_TEMPLATE_LABEL`).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Activity, AgeBand, Lesson, Question, Subject

SAFE_TEMPLATE_LABEL = "Safe template lesson: pre-written, not generated for this session."

_PLACEHOLDER = "{obj}"


@dataclass(frozen=True)
class _ActivitySpec:
    instruction: str
    answer_kind: str
    expected: str
    rubric: str
    hint: str
    difficulty: int


@dataclass(frozen=True)
class _TemplateSpec:
    title: str
    objective: str
    setup: str
    activities: tuple[_ActivitySpec, _ActivitySpec, _ActivitySpec]
    topic: str


def _a(
    instruction: str, expected: str, hint: str, difficulty: int, kind: str = "integer"
) -> _ActivitySpec:
    return _ActivitySpec(
        instruction=instruction,
        answer_kind=kind,
        expected=expected,
        rubric=f"Correct if the answer is {expected}.",
        hint=hint,
        difficulty=difficulty,
    )


_TEMPLATES: dict[tuple[AgeBand, Subject], _TemplateSpec] = {
    (AgeBand.B6_8, Subject.ARITHMETIC): _TemplateSpec(
        title="Counting with {obj}",
        objective="Add and take away small numbers",
        setup="Sit together and look at your {obj} items.",
        topic="adding and taking away small numbers",
        activities=(
            _a(
                "Pretend you have 3 {obj} items in one hand and 2 in the other. "
                "How many do you have in all?",
                "5",
                "Count 3, then keep counting 2 more.",
                1,
            ),
            _a(
                "You have 8 {obj} items and give away 3. How many are left?",
                "5",
                "Start at 8 and count back 3.",
                2,
            ),
            _a(
                "Line up 2 {obj} items, then 2 more, then 2 more. How many are there?",
                "6",
                "Count by twos: 2, 4, then one more step.",
                3,
            ),
        ),
    ),
    (AgeBand.B9_10, Subject.ARITHMETIC): _TemplateSpec(
        title="Number play with {obj}",
        objective="Add, subtract and find equal groups",
        setup="Sit together and think about your {obj} items.",
        topic="adding, taking away and equal groups",
        activities=(
            _a(
                "Pretend you have 12 {obj} items and find 7 more. How many do you have in all?",
                "19",
                "Add 10 first, then add the rest.",
                1,
            ),
            _a(
                "You have 25 {obj} items and give away 9. How many are left?",
                "16",
                "Take away 10, then add 1 back.",
                2,
            ),
            _a(
                "Make 4 rows with 3 {obj} items in each row. How many items are there in all?",
                "12",
                "Count by threes, four times.",
                3,
            ),
        ),
    ),
    (AgeBand.B11_12, Subject.ARITHMETIC): _TemplateSpec(
        title="Bigger numbers with {obj}",
        objective="Add, subtract and find equal groups with bigger numbers",
        setup="Sit together and think about your {obj} items.",
        topic="working with bigger numbers",
        activities=(
            _a(
                "Pretend you have 45 {obj} items and find 38 more. How many do you have in all?",
                "83",
                "Add 40 first, then add 5 more.",
                1,
            ),
            _a(
                "You have 100 {obj} items and give away 37. How many are left?",
                "63",
                "Take away 40, then add 3 back.",
                2,
            ),
            _a(
                "Make 6 rows with 8 {obj} items in each row. How many items are there in all?",
                "48",
                "Count by eights, six times.",
                3,
            ),
        ),
    ),
    (AgeBand.B6_8, Subject.MEASUREMENT): _TemplateSpec(
        title="Long and short with {obj}",
        objective="Compare lengths using objects as units",
        setup="Sit together and look at your {obj} items.",
        topic="comparing lengths with objects",
        activities=(
            _a(
                "Line A has 4 {obj} items. Line B has 2 items of the same size. "
                "Which line is longer, A or B?",
                "A",
                "The line with more items is longer.",
                1,
                "choice",
            ),
            _a(
                "Line up 3 {obj} items. Then line up 5. Which line has more items, 3 or 5?",
                "5",
                "Count each line one item at a time.",
                2,
            ),
            _a(
                "Each {obj} item is 1 hand long. A line has 6 items. How many hands long is it?",
                "6",
                "One item is one hand, so count the items.",
                3,
            ),
        ),
    ),
    (AgeBand.B9_10, Subject.MEASUREMENT): _TemplateSpec(
        title="Measuring with {obj}",
        objective="Measure and compare lengths using objects as units",
        setup="Sit together and think about your {obj} items.",
        topic="measuring and comparing lengths",
        activities=(
            _a(
                "Two lines of {obj} items have 9 and 6 items. "
                "How many more items long is the longer line?",
                "3",
                "Count up from 6 to 9.",
                1,
            ),
            _a(
                "Each {obj} item is 2 hands long. A line has 5 items. How many hands long is it?",
                "10",
                "Count by twos, five times.",
                2,
            ),
            _a(
                "A table is 12 {obj} items long and a mat is 7 items long. "
                "Which is shorter, the table or the mat?",
                "mat",
                "The smaller number of items is shorter.",
                3,
                "short_text",
            ),
        ),
    ),
    (AgeBand.B11_12, Subject.MEASUREMENT): _TemplateSpec(
        title="Length puzzles with {obj}",
        objective="Compare and calculate lengths using objects as units",
        setup="Sit together and think about your {obj} items.",
        topic="calculating lengths with objects",
        activities=(
            _a(
                "A path is 15 {obj} items long. You have covered 9 items. How many items are left?",
                "6",
                "Count on from 9 to 15.",
                1,
            ),
            _a(
                "Each {obj} item is 3 hands long. A line has 8 items. How many hands long is it?",
                "24",
                "Count by threes, eight times.",
                2,
            ),
            _a(
                "A shelf is 20 {obj} items long and a desk is 14 items long. "
                "How many items longer is the shelf?",
                "6",
                "Count up from 14 to 20.",
                3,
            ),
        ),
    ),
}


def available_templates() -> list[tuple[AgeBand, Subject]]:
    """Every (Age_Band, Subject) pair that has a curated Safe_Template."""
    return list(_TEMPLATES)


def build_safe_template(age_band: AgeBand, subject: Subject, obj: str) -> Lesson | None:
    """Return the labeled Safe_Template Lesson for the pair, or ``None`` if none exists.

    ``obj`` is one usable Object from the Facilitator's inventory; it is substituted for
    the placeholder so the Lesson is grounded in the submitted inputs (R-03.1).
    """
    spec = _TEMPLATES.get((age_band, subject))
    if spec is None:
        return None

    def fill(text: str) -> str:
        return text.replace(_PLACEHOLDER, obj)

    activities = [
        Activity(
            id=f"t{i + 1}",
            instruction=fill(s.instruction),
            facilitator_note="Stay nearby and let the learner work it out at their own pace.",
            required_objects=[obj],
            answer_kind=s.answer_kind,
            expected_answer=s.expected,
            rubric=s.rubric,
            hints=[s.hint],
            difficulty=s.difficulty,
        )
        for i, s in enumerate(spec.activities)
    ]
    return Lesson(
        source="safe_template",
        title=fill(spec.title)[:80],
        objective=spec.objective,
        objects=[obj],
        setup=f"{SAFE_TEMPLATE_LABEL} {fill(spec.setup)}"[:500],
        activities=activities,
        baseline_question=Question(
            id="baseline",
            topic=spec.topic,
            prompt=f"How confident are you about {spec.topic}?",
            scale_max=5,
        ),
        end_question=Question(
            id="end",
            topic=spec.topic,
            prompt=f"Now, how confident are you about {spec.topic}?",
            scale_max=5,
        ),
        estimated_minutes=5,
    )
