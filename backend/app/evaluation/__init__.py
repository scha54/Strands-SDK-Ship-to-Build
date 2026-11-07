"""Evaluation harness (task 10.4): synthetic cases, adversarial cases, latency and cost.

Run ``python -m app.evaluation`` for the stubbed suite. The live-model run is opt-in
(``--live`` plus ``IC_EVAL_LIVE=1``) and is always reported under its own label.
"""

from app.evaluation.harness import EvaluationReport, SuiteResult, run_stubbed_suite

__all__ = ["EvaluationReport", "SuiteResult", "run_stubbed_suite"]
