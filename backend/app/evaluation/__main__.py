"""CLI: ``python -m app.evaluation [--out FILE] [--live]``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from app.evaluation.harness import (
    DEFAULT_USD_PER_1K_TOKENS,
    EvaluationReport,
    run_live_suite,
    run_stubbed_suite,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation")
    parser.add_argument("--out", help="write the JSON report to this file")
    parser.add_argument(
        "--live",
        action="store_true",
        help="also run lesson cases against the live model (requires IC_EVAL_LIVE=1)",
    )
    parser.add_argument("--usd-per-1k-tokens", type=float, default=DEFAULT_USD_PER_1K_TOKENS)
    args = parser.parse_args(argv)

    stubbed = asyncio.run(run_stubbed_suite(usd_per_1k_tokens=args.usd_per_1k_tokens))
    live = None
    if args.live:
        if os.environ.get("IC_EVAL_LIVE") != "1":
            print("--live needs IC_EVAL_LIVE=1; skipping the live run.", file=sys.stderr)
        else:
            live = asyncio.run(run_live_suite(usd_per_1k_tokens=args.usd_per_1k_tokens))
    report = EvaluationReport(stubbed=stubbed, live=live)
    text = json.dumps(report.model_dump(mode="json"), indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(report.summary_text())
    return 0 if stubbed.adversarial_bypasses == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
