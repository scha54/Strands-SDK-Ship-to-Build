import { useState } from "react";

import type { AnswerResult, LearnerView } from "../../api/learning";

export const MAX_ANSWER_LENGTH = 2000;

export interface ActivityViewProps {
  view: LearnerView;
  result: AnswerResult | null;
  hint: string | null;
  busy: boolean;
  onSubmitAnswer: (answer: string) => void;
  onHint: () => void;
  onAdvance: (outcome: "completed" | "skipped") => void;
}

/**
 * One-Activity view with "n of N" progress, hint, answer, feedback and
 * clarification prompts (R-05.1, R-05.6, R-05.7, R-06.3). Nothing on this screen
 * is timed: the answer box has no countdown and nothing auto-submits (NFR-09).
 * Typed text lives in local state so it is retained when a save fails (R-10.9).
 */
export function ActivityView({
  view,
  result,
  hint,
  busy,
  onSubmitAnswer,
  onHint,
  onAdvance,
}: ActivityViewProps): React.JSX.Element {
  const activity = view.activity;
  const [text, setText] = useState("");
  const [emptyError, setEmptyError] = useState(false);

  if (activity === null) {
    return (
      <section className="ic-learning-screen">
        <p>All activities are done.</p>
      </section>
    );
  }

  const canContinue = result !== null && !result.clarification_requested;
  const numeric =
    activity.answer_kind === "integer" || activity.answer_kind === "decimal";

  return (
    <section aria-labelledby="activity-heading" className="ic-learning-screen">
      <h2 id="activity-heading">{view.title}</h2>
      <p data-testid="progress">{view.progress.label}</p>
      <p>{activity.instruction}</p>
      {activity.required_objects.length > 0 && (
        <p>Objects: {activity.required_objects.join(", ")}</p>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim() === "") {
            setEmptyError(true);
            return;
          }
          setEmptyError(false);
          onSubmitAnswer(text);
        }}
      >
        <label htmlFor="activity-answer">Your answer</label>
        <input
          id="activity-answer"
          type="text"
          inputMode={numeric ? "decimal" : "text"}
          autoComplete="off"
          maxLength={MAX_ANSWER_LENGTH}
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-invalid={emptyError}
          aria-describedby={emptyError ? "activity-answer-error" : undefined}
        />
        {emptyError && (
          <p id="activity-answer-error" role="alert">
            Please type an answer first.
          </p>
        )}
        <button type="submit" disabled={busy}>
          Check my answer
        </button>
        <button type="button" disabled={busy} onClick={onHint}>
          Show a hint
        </button>
      </form>

      {hint !== null && (
        <p data-testid="hint" role="status">
          Hint: {hint}
        </p>
      )}

      {result !== null && (
        <div data-testid="feedback" role="status" aria-live="polite">
          <p>{result.explanation}</p>
          {result.clarification_requested && (
            <p data-testid="clarification">
              {result.clarification_prompt ??
                "Can you tell me that another way?"}
            </p>
          )}
          {result.adjustment_note && <p>{result.adjustment_note}</p>}
          {activity.expected_answer && (
            <p data-testid="expected-answer">
              Expected answer: {activity.expected_answer}
            </p>
          )}
          {activity.rubric && <p>{activity.rubric}</p>}
        </div>
      )}

      <div>
        {canContinue && (
          <button type="button" disabled={busy} onClick={() => onAdvance("completed")}>
            Next
          </button>
        )}
        <button type="button" disabled={busy} onClick={() => onAdvance("skipped")}>
          Skip this activity
        </button>
      </div>
    </section>
  );
}
