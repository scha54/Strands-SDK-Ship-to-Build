"""Evaluation harness (task 10.4).

Covers R-12.2, R-12.6; NFR-05, NFR-09, NFR-10.
Runs the stubbed suite: >= 30 synthetic cases, pass rates, p50/p95 latency, cost per Session,
adversarial cases with no gate bypass, and a live run that is opt-in and labeled separately.
"""

from __future__ import annotations

import pytest
from app.evaluation import EvaluationReport, run_stubbed_suite
from app.evaluation.__main__ import main
from app.evaluation.harness import (
    COMPROMISED,
    INJECTED_OBJECTS,
    SuiteResult,
    oracle_violations,
    percentile,
)


@pytest.fixture
async def stubbed() -> SuiteResult:
    return await run_stubbed_suite()


async def test_at_least_thirty_synthetic_cases(stubbed: SuiteResult) -> None:
    """R-12.6, NFR-10: the suite covers at least 30 synthetic Lesson cases."""
    assert stubbed.lesson_cases >= 30
    assert stubbed.scaffold_cases >= 10
    assert stubbed.cases == len(stubbed.details)


async def test_pass_rates_are_reported_and_full_for_stub(stubbed: SuiteResult) -> None:
    """NFR-10: schema, grounding and safety pass rates, plus scaffold relevance."""
    assert stubbed.schema_pass_rate == 1.0
    assert stubbed.grounding_pass_rate == 1.0
    assert stubbed.safety_pass_rate == 1.0
    assert stubbed.composite_gate_pass_rate == 1.0
    assert stubbed.scaffold_relevance_rate == 1.0


async def test_latency_and_cost_figures(stubbed: SuiteResult) -> None:
    """NFR-05, NFR-09: p50/p95 latency and estimated cost per Session are recorded."""
    assert 0 < stubbed.latency_p50_ms <= stubbed.latency_p95_ms
    assert stubbed.tokens_per_session_p50 > 0
    assert 0 < stubbed.est_cost_usd_per_session_p50 <= stubbed.est_cost_usd_per_session_p95
    assert "illustrative" in stubbed.note  # stubbed figures are never presented as measured


async def test_adversarial_cases_do_not_bypass_gates(stubbed: SuiteResult) -> None:
    """NFR-10: injection, compromised-model and hostile-answer cases never get past a gate."""
    adversarial = [d for d in stubbed.details if d.category == "adversarial"]
    assert len(adversarial) >= len(INJECTED_OBJECTS) + len(COMPROMISED)
    assert stubbed.adversarial_bypasses == 0
    assert all(d.checks["blocked"] and not d.checks["bypass"] for d in adversarial)


async def test_stubbed_and_live_results_are_labeled_separately(stubbed: SuiteResult) -> None:
    """R-12.6, NFR-09: the live result is absent unless opted in and never merged."""
    report = EvaluationReport(stubbed=stubbed)
    assert report.live is None
    assert report.stubbed.label == "stubbed"
    assert "LIVE: not run" in report.summary_text()


def test_live_flag_without_env_opt_in_skips_live_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The live run needs --live and IC_EVAL_LIVE=1; otherwise no model is contacted."""
    monkeypatch.delenv("IC_EVAL_LIVE", raising=False)
    assert main(["--live"]) == 0
    captured = capsys.readouterr()
    assert "skipping the live run" in captured.err
    assert "LIVE: not run" in captured.out


def test_oracle_detects_violations_so_zero_bypasses_is_meaningful() -> None:
    """The bypass oracle flags what the gates must catch (guards against a vacuous pass)."""
    from app.domain.models import Lesson, Question, StoryDraft  # noqa: PLC0415
    from app.evaluation.harness import _draft  # noqa: PLC0415

    draft = StoryDraft.model_validate(_draft(required_objects=["laptop"]))
    q = Question(id="q", topic="count", prompt="How many?", scale_max=5)
    lesson = Lesson(
        source="generated",
        title="t",
        objective="o",
        objects=["stone"],
        setup="s",
        activities=draft.activities,
        baseline_question=q,
        end_question=q,
        estimated_minutes=5,
    )
    assert oracle_violations(lesson, ["stone", "leaf"])


def test_percentile_nearest_rank() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 95) == 4
