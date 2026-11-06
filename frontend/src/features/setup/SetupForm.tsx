import { useId, useState } from "react";

import type { CreateSessionRequest } from "../../api/types";
import "./SetupForm.css";
import { DEMO_PRESET, DEMO_PRESET_OBJECTS_TEXT } from "./demoPreset";
import { AGE_BAND_OPTIONS, SUBJECT_OPTIONS } from "./subjects";
import {
  MAX_OBJECTS,
  MAX_OBJECT_LENGTH,
  type SetupFieldErrors,
  type SetupFormValues,
  validateSetup,
} from "./validateSetup";

/**
 * Setup (start page) feature (R-01).
 *
 * Collects the Age_Band, Subject and Objects an adult Facilitator enters to
 * start a Session. There are deliberately no child-identity fields: the form
 * asks only for the three contract inputs (R-01.4).
 *
 * Behaviour:
 * - Single-select Age_Band with exactly three options and Subject selector,
 *   both with no preselection; Objects entry for 1 to 20 names of 1 to 50
 *   characters; a Demo_Mode preset control (R-01.1).
 * - On submit, fields are validated and per-field errors are shown next to the
 *   relevant control while every entered value is retained (R-01.3, R-02.2).
 * - The Demo_Mode preset fills all three fields and leaves them editable
 *   (R-01.5).
 * - When session creation fails for a non-validation reason, a "Session could
 *   not be started" message is shown, values are retained and the Facilitator
 *   can resubmit (R-01.6).
 * - Every control has a programmatically associated label, and errors are
 *   wired to their controls via aria-describedby (R-09.3; NFR-03).
 */

const EMPTY_VALUES: SetupFormValues = {
  ageBand: "",
  subject: "",
  objectsText: "",
};

const GENERIC_FAILURE_MESSAGE =
  "Session could not be started. Please try again.";

export interface SetupFormProps {
  /**
   * Starts a Session from validated inputs. Rejecting (or throwing) signals a
   * non-validation failure, which surfaces the generic retryable error while
   * retaining the entered values (R-01.6).
   */
  onSubmit: (request: CreateSessionRequest) => Promise<void>;
}

export function SetupForm({ onSubmit }: SetupFormProps): React.JSX.Element {
  const [values, setValues] = useState<SetupFormValues>(EMPTY_VALUES);
  const [errors, setErrors] = useState<SetupFieldErrors>({});
  const [submitFailed, setSubmitFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const baseId = useId();
  const ageErrorId = `${baseId}-age-error`;
  const subjectErrorId = `${baseId}-subject-error`;
  const objectsErrorId = `${baseId}-objects-error`;
  const objectsHintId = `${baseId}-objects-hint`;
  const formErrorId = `${baseId}-form-error`;

  function applyPreset(): void {
    setValues({
      ageBand: DEMO_PRESET.ageBand,
      subject: DEMO_PRESET.subject,
      objectsText: DEMO_PRESET_OBJECTS_TEXT,
    });
    // Filling the preset clears any stale errors but keeps fields editable.
    setErrors({});
    setSubmitFailed(false);
  }

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    const result = validateSetup(values);
    setErrors(result.errors);

    if (!result.request) {
      // Validation errors are shown per field; the generic failure is hidden.
      setSubmitFailed(false);
      return;
    }

    setSubmitting(true);
    setSubmitFailed(false);
    try {
      await onSubmit(result.request);
    } catch {
      // Non-validation failure: keep all entered values and allow resubmission.
      setSubmitFailed(true);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="ic-setup ic-stack" onSubmit={handleSubmit} noValidate>
      <fieldset className="ic-setup__fieldset">
        <legend className="ic-setup__legend">Age band</legend>
        <div
          className="ic-setup__options"
          role="radiogroup"
          aria-describedby={errors.ageBand ? ageErrorId : undefined}
        >
          {AGE_BAND_OPTIONS.map((option) => (
            <label key={option.value} className="ic-setup__option">
              <input
                type="radio"
                name="age-band"
                value={option.value}
                checked={values.ageBand === option.value}
                onChange={() =>
                  setValues((prev) => ({ ...prev, ageBand: option.value }))
                }
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
        {errors.ageBand ? (
          <p id={ageErrorId} className="ic-setup__error" role="alert">
            {errors.ageBand}
          </p>
        ) : null}
      </fieldset>

      <div className="ic-setup__field">
        <label className="ic-setup__label" htmlFor={`${baseId}-subject`}>
          Subject
        </label>
        <select
          id={`${baseId}-subject`}
          className="ic-setup__select"
          value={values.subject}
          aria-describedby={errors.subject ? subjectErrorId : undefined}
          onChange={(event) =>
            setValues((prev) => ({
              ...prev,
              subject: event.target.value as SetupFormValues["subject"],
            }))
          }
        >
          <option value="">Choose a subject…</option>
          {SUBJECT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {errors.subject ? (
          <p id={subjectErrorId} className="ic-setup__error" role="alert">
            {errors.subject}
          </p>
        ) : null}
      </div>

      <div className="ic-setup__field">
        <label className="ic-setup__label" htmlFor={`${baseId}-objects`}>
          Objects
        </label>
        <p id={objectsHintId} className="ic-setup__hint">
          Enter one object per line. Add {MAX_OBJECTS} at most, each up to{" "}
          {MAX_OBJECT_LENGTH} characters.
        </p>
        <textarea
          id={`${baseId}-objects`}
          className="ic-setup__textarea"
          rows={6}
          value={values.objectsText}
          aria-describedby={
            errors.objects
              ? `${objectsHintId} ${objectsErrorId}`
              : objectsHintId
          }
          onChange={(event) =>
            setValues((prev) => ({ ...prev, objectsText: event.target.value }))
          }
        />
        {errors.objects ? (
          <p id={objectsErrorId} className="ic-setup__error" role="alert">
            {errors.objects}
          </p>
        ) : null}
      </div>

      <div className="ic-setup__actions">
        <button
          type="button"
          className="ic-setup__preset"
          onClick={applyPreset}
        >
          Fill Demo Mode preset
        </button>
        <button type="submit" className="ic-setup__submit" disabled={submitting}>
          {submitting ? "Starting…" : "Start session"}
        </button>
      </div>

      {submitFailed ? (
        <p id={formErrorId} className="ic-setup__error" role="alert">
          {GENERIC_FAILURE_MESSAGE}
        </p>
      ) : null}
    </form>
  );
}

export default SetupForm;
