import type { LearningSummary } from "../../api/learning";

export const NOT_VALIDATED_WARNING =
  "This is an observed difference only. It is not a validated educational assessment.";

export interface DifferenceDisplay {
  /** True only when both the baseline and end answers were given (R-07.3). */
  show: boolean;
  baseline?: number;
  end?: number;
  difference?: number;
  /** Always present with a shown difference (R-07.5). */
  warning?: string;
  /** Neutral wording; an "improvement" claim only for a strictly positive difference (R-07.4). */
  statement?: string;
}

/**
 * Decides what the summary may say about the baseline/end difference.
 * The difference is recomputed from the two answers rather than trusted, and
 * is never shown when either answer was skipped.
 */
export function describeDifference(summary: LearningSummary): DifferenceDisplay {
  const { baseline, end_answer: end } = summary;
  const skipped = summary.baseline_skipped === true || summary.end_skipped === true;
  if (skipped || typeof baseline !== "number" || typeof end !== "number") {
    return { show: false };
  }
  const difference = end - baseline;
  const warning = summary.warning ?? NOT_VALIDATED_WARNING;
  const statement =
    difference > 0
      ? `Your end-check answer was ${difference} higher than your baseline answer.`
      : `Baseline answer ${baseline}, end-check answer ${end}.`;
  return { show: true, baseline, end, difference, warning, statement };
}
