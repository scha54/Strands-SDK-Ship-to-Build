import { useState } from "react";

import type { QuestionView } from "../../api/learning";

export interface ScaleQuestionProps {
  heading: string;
  question: QuestionView;
  busy: boolean;
  /** Submit a numeric answer, or `null` when the Learner skips. */
  onSubmit: (answer: number | null) => void;
}

/**
 * Answer-or-skip scale question shared by the baseline and end check.
 * There is no timer or countdown anywhere on this screen (R-05.1 / NFR-09).
 * The selection is local state, so it survives a failed save (R-10.9).
 */
export function ScaleQuestion({
  heading,
  question,
  busy,
  onSubmit,
}: ScaleQuestionProps): React.JSX.Element {
  const [value, setValue] = useState<number | null>(null);
  const options = Array.from({ length: question.scale_max + 1 }, (_, i) => i);

  return (
    <section aria-labelledby="scale-heading" className="ic-learning-screen">
      <h2 id="scale-heading">{heading}</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (value !== null) onSubmit(value);
        }}
      >
        <fieldset>
          <legend>{question.prompt}</legend>
          <p>
            Pick a number from 0 to {question.scale_max}.
          </p>
          {options.map((n) => (
            <label key={n} className="ic-scale-option">
              <input
                type="radio"
                name={`scale-${question.question_id}`}
                value={n}
                checked={value === n}
                onChange={() => setValue(n)}
              />
              {n}
            </label>
          ))}
        </fieldset>
        <button type="submit" disabled={busy || value === null}>
          Submit answer
        </button>
        {question.can_skip && (
          <button type="button" disabled={busy} onClick={() => onSubmit(null)}>
            Skip this question
          </button>
        )}
      </form>
    </section>
  );
}
