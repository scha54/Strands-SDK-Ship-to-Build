"""Learning-loop routes: baseline, answers, hints, advance, end check and summary (task 8.8).

Covers R-05.2, R-05.3, R-05.4, R-05.5, R-05.6, R-05.7, R-05.8, R-07.1, R-07.2, R-07.6, R-08.3,
R-10.9; NFR-02, NFR-05.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest
from app.adapters.bedrock import ResilientModelClient, StubModel
from app.adapters.session_store import InMemorySessionStore
from app.agents.assessment import AssessmentSpecialist
from app.agents.curriculum import CurriculumSpecialist
from app.agents.environment import EnvironmentSpecialist
from app.agents.orchestrator import Orchestrator
from app.agents.storytelling import StorytellingSpecialist
from app.config import Settings
from app.domain.models import (
    Activity,
    Assessment,
    AssessmentStatus,
    Lesson,
    Question,
    SessionRecord,
)
from app.main import create_app
from app.services.assessment_service import AssessmentService, contains_diagnostic_language
from app.services.learning_loop import LearningLoopService, end_question_for, leaks_answer
from app.services.lesson_service import LessonService
from app.services.session_service import SessionService
from fastapi.testclient import TestClient

API = "/api/v1/sessions"
FREE_TEXT_ANSWER = "Stones are heavy because they are made of rock"


def _activity(i: int, kind: str, expected: str, **kw: Any) -> Activity:
    data: dict[str, Any] = {
        "id": f"a{i}",
        "instruction": "Count the stones. How many are there?",
        "facilitator_note": f"SECRETNOTE{i}",
        "required_objects": ["stone"],
        "answer_kind": kind,
        "expected_answer": expected,
        "rubric": f"RUBRIC{i}",
        "hints": ["Touch each stone as you count."],
        "difficulty": 2,
    }
    data.update(kw)
    return Activity.model_validate(data)


def _lesson(first: Activity | None = None) -> Lesson:
    return Lesson(
        source="generated",
        title="Stone counting",
        objective="Count small groups",
        objects=["stone"],
        setup="Put your stones on the table.",
        activities=[
            first or _activity(0, "integer", "3", hints=["Touch each stone.", "It is 3 stones."]),
            _activity(1, "integer", "5"),
            _activity(2, "short_text", "stone"),
        ],
        baseline_question=Question(
            id="baseline", topic="counting", prompt="How sure?", scale_max=5
        ),
        end_question=Question(id="end", topic="counting", prompt="Now, how sure?", scale_max=5),
        estimated_minutes=5,
    )


class FlakyStore(InMemorySessionStore):
    """Store whose next ``fail_puts`` writes fail, to test persist-failure retry."""

    fail_puts = 0

    def put_if_version(self, s: SessionRecord, expected: int) -> None:
        if self.fail_puts > 0:
            self.fail_puts -= 1
            raise OSError("store down")
        super().put_if_version(s, expected)


class FakeAssessor:
    def __init__(self, result: Assessment | Exception | None = None) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self, activity: Activity, answer: str) -> Assessment:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        assert self.result is not None
        return self.result


@dataclass
class Ctx:
    client: TestClient
    store: FlakyStore
    sid: str
    headers: dict[str, str]
    assessor: FakeAssessor

    def url(self, path: str) -> str:
        return f"{API}/{self.sid}/{path}"

    def record(self) -> SessionRecord:
        from app.adapters.session_store import SystemClock

        return self.store.get(self.sid, SystemClock().now())

    def baseline(self, value: int | None = 2) -> Any:
        body = {"skipped": True} if value is None else {"answer": value}
        return self.client.post(self.url("baseline"), json=body, headers=self.headers)

    def answer(self, text: str, key: str = "k1") -> Any:
        return self.client.post(
            self.url("answers"),
            json={"answer": text},
            headers={**self.headers, "Idempotency-Key": key},
        )

    def advance(self, activity_id: str, outcome: str = "completed") -> Any:
        return self.client.post(
            self.url("advance"),
            json={"activity_id": activity_id, "outcome": outcome},
            headers=self.headers,
        )

    def hint(self) -> Any:
        return self.client.post(self.url("hint"), headers=self.headers)

    def get(self, path: str) -> Any:
        return self.client.get(self.url(path), headers=self.headers)

    def start(self, value: int | None = 2) -> None:
        assert self.baseline(value).status_code == 200


def _ctx(lesson: Lesson | None = None, assessor: FakeAssessor | None = None) -> Ctx:
    settings = Settings(model_retry_backoff_seconds=0, specialist_retries=0)
    store = FlakyStore()
    sessions = SessionService(store)
    client_model = ResilientModelClient(StubModel(), settings)
    orchestrator = Orchestrator(
        environment=EnvironmentSpecialist(client_model),
        curriculum=CurriculumSpecialist(client_model),
        storytelling=StorytellingSpecialist(client_model),
        assessment=AssessmentSpecialist(client_model),
        settings=settings,
    )
    fake = assessor or FakeAssessor(
        Assessment(status=AssessmentStatus.CORRECT, explanation="Good.", confidence=0.9)
    )
    learning = LearningLoopService(store, AssessmentService(fake), settings)
    app = create_app(
        settings,
        session_service=sessions,
        lesson_service=LessonService(store, orchestrator, settings),
        learning_service=learning,
    )
    client = TestClient(app)
    body = client.post(
        API,
        json={"age_band": "6-8", "subject": "arithmetic_counting", "objects": ["stone", "leaf"]},
    ).json()
    sid = body["session_id"]
    rec = store.get(sid, sessions._now())
    store.put_if_version(
        rec.model_copy(update={"state": "ready", "lesson": lesson or _lesson()}), rec.version
    )
    return Ctx(client, store, sid, {"Authorization": f"Bearer {body['capability_token']}"}, fake)


# --- baseline (R-07.1, R-07.6) ----------------------------------------------------------------


def test_baseline_is_shown_first_and_blocks_other_content() -> None:
    """R-07.1: the baseline question is served first; answers are refused until it is handled."""
    ctx = _ctx()
    question = ctx.get("baseline").json()
    assert question["prompt"] and question["can_skip"] is True and question["scale_max"] == 5
    early = ctx.answer("3")
    assert early.status_code == 409 and early.json()["code"] == "invalid_state"
    assert ctx.hint().status_code == 409
    res = ctx.baseline(3)
    body = res.json()
    assert res.status_code == 200 and body["state"] == "active"
    assert body["view"]["progress"]["label"] == "1 of 3"
    assert (
        "expected_answer" not in body["view"]["activity"]
        or body["view"]["activity"]["expected_answer"] is None
    )
    assert ctx.record().baseline == 3


def test_baseline_skip_continues_without_data_loss() -> None:
    """R-07.6: skipping the baseline continues the lesson and records the skip."""
    ctx = _ctx()
    res = ctx.baseline(None)
    assert res.status_code == 200 and res.json()["state"] == "active"
    assert ctx.answer("3").status_code == 200
    summary = ctx.get("summary").json()
    assert summary["baseline_skipped"] is True and summary["baseline"] is None


def test_baseline_rejects_ambiguous_or_out_of_scale_input_unchanged() -> None:
    """R-07.1, NFR-02: answer+skip, neither or out-of-scale input is refused unchanged."""
    ctx = _ctx()
    before = ctx.record()
    for body in ({"answer": 2, "skipped": True}, {}, {"answer": 9}):
        res = ctx.client.post(ctx.url("baseline"), json=body, headers=ctx.headers)
        assert res.status_code == 422
    assert ctx.record() == before


def test_baseline_repeat_is_replayed_not_reapplied() -> None:
    """R-05.3, NFR-05: a retried identical baseline succeeds once; a different one is refused."""
    ctx = _ctx()
    ctx.start(3)
    assert ctx.baseline(3).status_code == 200
    assert ctx.baseline(4).status_code == 409
    assert ctx.record().baseline == 3


# --- answers (R-05.2 to R-05.4) ---------------------------------------------------------------


def test_deterministic_answer_is_graded_within_two_seconds_without_model() -> None:
    """R-05.2, NFR-02: exact answers are graded fast with no specialist call."""
    ctx = _ctx()
    ctx.start()
    started = time.perf_counter()
    res = ctx.answer("3")
    assert time.perf_counter() - started < 2
    body = res.json()
    assert res.status_code == 200 and body["status"] == "correct"
    assert ctx.assessor.calls == 0
    activity = body["view"]["activity"]
    assert activity["expected_answer"] == "3" and activity["rubric"] == "RUBRIC0"
    assert "SECRETNOTE" not in res.text


def test_answer_is_idempotent_and_conflicting_payload_rejected() -> None:
    """R-05.3: same key applies once and replays; same key with another payload is a 409."""
    ctx = _ctx()
    ctx.start()
    first = ctx.answer("3", "key-1")
    again = ctx.answer("3", "key-1")
    assert first.json()["replayed"] is False and again.json()["replayed"] is True
    assert again.json()["status"] == first.json()["status"]
    rec = ctx.record()
    assert len(rec.answers) == 1 and rec.activity_status[0].attempts == 1
    clash = ctx.answer("4", "key-1")
    assert clash.status_code == 409 and clash.json()["code"] == "idempotency_key_conflict"
    assert len(ctx.record().answers) == 1


@pytest.mark.parametrize(
    ("text", "code"),
    [("   ", "invalid_answer"), ("x" * 2001, "validation_error"), ("banana", "invalid_answer")],
)
def test_invalid_answers_leave_progress_unchanged(text: str, code: str) -> None:
    """R-05.4: empty, over-long and wrong-format answers are rejected; nothing changes."""
    ctx = _ctx()
    ctx.start()
    before = ctx.record()
    res = ctx.answer(text, "bad")
    assert res.status_code == 422 and res.json()["code"] == code
    assert ctx.record() == before


def test_empty_string_answer_rejected_unchanged() -> None:
    """R-05.4: a zero-length answer is rejected with progress unchanged."""
    ctx = _ctx()
    ctx.start()
    before = ctx.record()
    assert ctx.answer("").status_code == 422
    assert ctx.record() == before


def test_unclear_answers_request_clarification_then_exclude() -> None:
    """R-06.3, R-06.4: unclear is never marked wrong; the third is excluded; skip/hint offered."""
    ctx = _ctx()
    ctx.start()
    for n in (1, 2):
        body = ctx.answer("3 or 4", f"u{n}").json()
        assert body["status"] == "unassessable" and body["clarification_requested"] is True
        assert body["view"]["activity"]["expected_answer"] is None
    third = ctx.answer("3 or 4", "u3").json()
    assert third["status"] == "unassessable" and third["excluded_from_mastery"] is True
    assert third["offer_skip_or_hint"] is True
    assert ctx.record().answers == []
    assert "not enough answers" in ctx.get("summary").json()["provisional_estimate"]


def test_assessment_failure_returns_retryable_error_unchanged() -> None:
    """R-05.4, NFR-05: a failed specialist call writes nothing and can be retried."""
    ctx = _ctx(_lesson(_activity(0, "short_text", FREE_TEXT_ANSWER)), FakeAssessor(RuntimeError()))
    ctx.start()
    before = ctx.record()
    res = ctx.answer("rocks are heavy")
    assert res.status_code == 503 and res.json()["code"] == "assessment_unavailable"
    assert ctx.record() == before


def test_misconception_adapts_next_activity_and_reports_it() -> None:
    """R-06.2: a misconception lowers the next Activity's difficulty and is reported."""
    result = Assessment(
        status=AssessmentStatus.SUPPORT,
        explanation="Let's look again.",
        misconception="Thinks heavier means bigger.",
        suggested_scaffold="Hold two stones and compare.",
        confidence=0.8,
    )
    first = _activity(0, "short_text", FREE_TEXT_ANSWER)
    ctx = _ctx(_lesson(first), FakeAssessor(result))
    ctx.start()
    body = ctx.answer("rocks are bigger").json()
    assert ctx.assessor.calls == 1 and body["adjustment_note"]
    assert not contains_diagnostic_language(body["explanation"] + body["adjustment_note"])
    assert ctx.record().lesson.activities[1].difficulty == 1  # type: ignore[union-attr]
    assert ctx.record().lesson.activities[1].id == "a1"  # type: ignore[union-attr]


# --- hints (R-05.5) ---------------------------------------------------------------------------


def test_hint_has_no_answer_text_and_status_unchanged() -> None:
    """R-05.5: hints skip any scaffold that holds the expected answer; status stays pending."""
    ctx = _ctx()
    ctx.start()
    for _ in range(3):
        body = ctx.hint().json()
        assert "3" not in body["hint"].split() and "It is 3 stones." != body["hint"]
        assert body["activity_status"] == "pending"
    rec = ctx.record()
    assert rec.activity_status[0].status == "pending" and rec.answers == []
    assert rec.current_index == 0


def test_hint_falls_back_to_generic_scaffold_when_all_hints_leak() -> None:
    """R-05.5: if every stored hint leaks the answer, a generic scaffold is returned."""
    leaky = _activity(0, "integer", "3", hints=["The answer is 3."])
    ctx = _ctx(_lesson(leaky))
    ctx.start()
    hint = ctx.hint().json()["hint"]
    assert "3" not in hint


def test_leaks_answer_detects_text_and_numeric_forms() -> None:
    """R-05.5: verbatim and numerically equal tokens count as leaks."""
    assert leaks_answer("It is 3 stones", "3")
    assert leaks_answer("Maybe three-point-zero: 3.0", "3")
    assert leaks_answer("The stone is the answer", "stone")
    assert not leaks_answer("Count each one slowly", "3")
    assert not leaks_answer("Try 13", "3")


# --- advance (R-05.6, R-05.7, R-10.9) ---------------------------------------------------------


def test_advance_persists_status_then_moves_on() -> None:
    """R-05.6: completed/skipped is persisted and the next Activity is shown as 'n of N'."""
    ctx = _ctx()
    ctx.start()
    assert ctx.advance("a0").status_code == 409  # not answered yet
    ctx.answer("3")
    res = ctx.advance("a0")
    body = res.json()
    assert res.status_code == 200 and body["view"]["progress"]["label"] == "2 of 3"
    assert body["view"]["activity"]["id"] == "a1" and body["finished"] is False
    again = ctx.advance("a0")  # retry after a lost response
    assert again.status_code == 200 and again.json()["view"]["activity"]["id"] == "a1"
    skip = ctx.advance("a1", "skipped").json()
    assert skip["view"]["progress"]["label"] == "3 of 3"
    rec = ctx.record()
    assert [s.status for s in rec.activity_status] == ["completed", "skipped", "pending"]
    assert ctx.advance("a0", "skipped").status_code == 409


def test_persist_failure_keeps_current_activity_and_allows_retry() -> None:
    """R-05.7, R-10.9: a failed save reports an error, keeps the Activity and can be retried."""
    ctx = _ctx()
    ctx.start()
    ctx.answer("3")
    ctx.store.fail_puts = 1
    failed = ctx.advance("a0")
    assert failed.status_code == 503 and failed.json()["code"] == "persist_failed"
    rec = ctx.record()
    assert rec.current_index == 0 and rec.activity_status[0].status == "pending"
    retry = ctx.advance("a0")
    assert retry.status_code == 200 and ctx.record().current_index == 1


# --- end check and summary (R-05.8, R-07.2 to R-07.5) -----------------------------------------


def _finish_activities(ctx: Ctx) -> None:
    ctx.answer("3", "f0")
    ctx.advance("a0")
    ctx.answer("5", "f1")
    ctx.advance("a1")
    ctx.answer("stone", "f2")
    res = ctx.advance("a2")
    assert res.json()["finished"] is True and res.json()["state"] == "end_check"


def test_end_check_same_topic_and_scale_with_different_wording() -> None:
    """R-07.2: the End_Question matches topic and scale but not the baseline wording."""
    ctx = _ctx()
    ctx.start()
    assert ctx.get("end-check").status_code == 409  # not open yet
    _finish_activities(ctx)
    base = ctx.get("baseline")
    assert base.status_code == 409  # baseline closed
    end = ctx.get("end-check").json()
    lesson = ctx.record().lesson
    assert lesson is not None
    assert end["topic"] == lesson.baseline_question.topic
    assert end["scale_max"] == lesson.baseline_question.scale_max
    assert end["prompt"] != lesson.baseline_question.prompt


def test_end_question_wording_is_forced_to_differ() -> None:
    """R-07.2: identical stored wording is rewritten; topic and scale are aligned."""
    lesson = _lesson()
    same = lesson.model_copy(
        update={
            "end_question": Question(
                id="end", topic="other", prompt=lesson.baseline_question.prompt, scale_max=4
            )
        }
    )
    q = end_question_for(same)
    assert q.prompt != same.baseline_question.prompt
    assert q.topic == same.baseline_question.topic and q.scale_max == 5


def test_summary_shows_difference_only_when_both_answered() -> None:
    """R-05.8, R-06.6, R-07.3: concepts, next step, provisional estimate and warning."""
    ctx = _ctx()
    ctx.start(2)
    _finish_activities(ctx)
    done = ctx.client.post(ctx.url("end-check"), json={"answer": 4}, headers=ctx.headers)
    assert done.status_code == 200 and done.json()["state"] == "completed"
    summary = ctx.get("summary").json()
    assert summary["baseline"] == 2 and summary["end_answer"] == 4 and summary["difference"] == 2
    assert "not a validated" in summary["warning"]
    assert summary["concepts_practiced"] and len(summary["next_steps"]) >= 1
    assert summary["provisional_estimate"].startswith("Provisional estimate")
    assert not contains_diagnostic_language(summary["provisional_estimate"])
    # retried identical end check is replayed, a different one is refused
    assert (
        ctx.client.post(ctx.url("end-check"), json={"answer": 4}, headers=ctx.headers).status_code
        == 200
    )
    assert (
        ctx.client.post(ctx.url("end-check"), json={"answer": 1}, headers=ctx.headers).status_code
        == 409
    )


@pytest.mark.parametrize(("baseline", "end"), [(None, 4), (2, None), (None, None)])
def test_summary_has_no_difference_when_either_skipped(
    baseline: int | None, end: int | None
) -> None:
    """R-07.4: a skipped question means no difference, no warning-backed claim, skip is named."""
    ctx = _ctx()
    ctx.start(baseline)
    _finish_activities(ctx)
    body = {"skipped": True} if end is None else {"answer": end}
    assert ctx.client.post(ctx.url("end-check"), json=body, headers=ctx.headers).status_code == 200
    summary = ctx.get("summary").json()
    assert summary["difference"] is None and summary["warning"] is None
    assert summary["baseline_skipped"] is (baseline is None)
    assert summary["end_skipped"] is (end is None)
    assert summary["next_steps"]


def test_zero_difference_is_reported_as_value_only() -> None:
    """R-07.5: a zero difference shows the value and the warning with no improvement wording."""
    ctx = _ctx()
    ctx.start(3)
    _finish_activities(ctx)
    ctx.client.post(ctx.url("end-check"), json={"answer": 3}, headers=ctx.headers)
    summary = ctx.get("summary").json()
    assert summary["difference"] == 0 and summary["warning"]
    assert "improve" not in str(summary).lower()


# --- stop and auth (R-08.3) -------------------------------------------------------------------


def test_all_writes_rejected_after_stop_but_summary_readable() -> None:
    """R-08.3: after Stop, baseline/answers/hint/advance/end-check return session_stopped."""
    ctx = _ctx()
    ctx.start()
    assert ctx.client.post(ctx.url("stop"), headers=ctx.headers).status_code == 200
    before = ctx.record()
    responses = [
        ctx.baseline(1),
        ctx.answer("3", "after-stop"),
        ctx.hint(),
        ctx.advance("a0"),
        ctx.client.post(ctx.url("end-check"), json={"answer": 1}, headers=ctx.headers),
    ]
    for res in responses:
        assert res.status_code == 409 and res.json()["code"] == "session_stopped"
    assert ctx.record() == before
    assert ctx.get("summary").status_code == 200
    assert ctx.get("learner-view").status_code == 200


def test_routes_require_capability_token() -> None:
    """NFR-02: learning routes are not reachable without the token."""
    ctx = _ctx()
    res = ctx.client.post(ctx.url("hint"))
    assert res.status_code == 401
