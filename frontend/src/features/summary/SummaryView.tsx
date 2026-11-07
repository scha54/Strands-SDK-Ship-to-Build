import type { LearningSummary } from "../../api/learning";
import { describeDifference } from "./differenceRule";

export interface SummaryViewProps {
  summary: LearningSummary;
}

/** Session summary: concepts, next steps and the observed difference (R-05.8, R-07.3 to R-07.5). */
export function SummaryView({ summary }: SummaryViewProps): React.JSX.Element {
  const diff = describeDifference(summary);
  return (
    <section aria-labelledby="summary-heading" className="ic-learning-screen">
      <h2 id="summary-heading">Session summary</h2>

      <h3>Concepts practiced</h3>
      {(summary.concepts_practiced ?? []).length > 0 ? (
        <ul>
          {(summary.concepts_practiced ?? []).map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      ) : (
        <p>No concepts were practiced in this session.</p>
      )}

      <h3>Next steps</h3>
      <ul>
        {(summary.next_steps ?? []).map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>

      {summary.provisional_estimate && (
        <p data-testid="provisional">
          Provisional estimate: {summary.provisional_estimate}
        </p>
      )}

      {diff.show && (
        <div data-testid="difference">
          <p>{diff.statement}</p>
          <p data-testid="difference-value">
            Observed difference: {diff.difference}
          </p>
          <p data-testid="not-validated-warning">{diff.warning}</p>
        </div>
      )}
    </section>
  );
}
