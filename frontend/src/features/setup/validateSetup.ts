// Client-side validation for the setup form.
//
// Mirrors the backend contract bounds so the Facilitator gets per-field errors
// before a request is sent, while the backend remains the authority (R-01.3,
// R-02.2). The Objects field is multi-line text: each non-empty line is one
// Object. Errors name the specific limit that failed (empty, name too long,
// too many objects) and the caller retains all entered values regardless of
// the outcome (R-01.3; NFR-02).
import type { AgeBand, CreateSessionRequest, Subject } from "../../api/types";

export const MAX_OBJECTS = 20;
export const MAX_OBJECT_LENGTH = 50;

/** The raw, user-entered form state. Values are always retained on error. */
export interface SetupFormValues {
  ageBand: AgeBand | "";
  subject: Subject | "";
  /** Multi-line text; one Object per non-empty line. */
  objectsText: string;
}

/** Per-field validation messages. A missing key means that field is valid. */
export interface SetupFieldErrors {
  ageBand?: string;
  subject?: string;
  objects?: string;
}

export interface SetupValidationResult {
  errors: SetupFieldErrors;
  /** Present only when there are no field errors. */
  request?: CreateSessionRequest;
}

/** Split the Objects textarea into trimmed, non-empty lines (entered order). */
export function parseObjectLines(objectsText: string): string[] {
  return objectsText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function validateSetup(values: SetupFormValues): SetupValidationResult {
  const errors: SetupFieldErrors = {};

  if (values.ageBand === "") {
    errors.ageBand = "Select an age band to continue.";
  }
  if (values.subject === "") {
    errors.subject = "Select a subject to continue.";
  }

  const objects = parseObjectLines(values.objectsText);
  if (objects.length === 0) {
    errors.objects = "Enter at least one object.";
  } else if (objects.length > MAX_OBJECTS) {
    errors.objects = `Enter at most ${MAX_OBJECTS} objects (you entered ${objects.length}).`;
  } else {
    const tooLong = objects.find((name) => name.length > MAX_OBJECT_LENGTH);
    if (tooLong !== undefined) {
      errors.objects = `Each object name must be ${MAX_OBJECT_LENGTH} characters or fewer. "${tooLong.slice(0, MAX_OBJECT_LENGTH)}…" is too long.`;
    }
  }

  if (Object.keys(errors).length > 0) {
    return { errors };
  }

  // Safe to narrow: the empty-string branches above are the only "" cases.
  const request: CreateSessionRequest = {
    age_band: values.ageBand as AgeBand,
    subject: values.subject as Subject,
    objects,
    language: "en",
  };
  return { errors, request };
}
