// Setup form option metadata.
//
// The Age_Band and Subject enums come from the generated backend contract
// (R-04.3; NFR-02). Here we pair each enum value with a human-readable label
// for the start page controls (R-01.1). Labels are the single UI-facing source
// of text so the control and its accessible name stay in sync (R-09.3).
import type { AgeBand, Subject } from "../../api/types";

export interface Option<T extends string> {
  readonly value: T;
  readonly label: string;
}

/** The three Age_Band options, in display order (R-01.1). */
export const AGE_BAND_OPTIONS: ReadonlyArray<Option<AgeBand>> = [
  { value: "6-8", label: "6 to 8 years" },
  { value: "9-10", label: "9 to 10 years" },
  { value: "11-12", label: "11 to 12 years" },
];

/** Supported subjects, in display order (R-01.1). */
export const SUBJECT_OPTIONS: ReadonlyArray<Option<Subject>> = [
  { value: "arithmetic_counting", label: "Arithmetic / counting" },
  { value: "intro_measurement", label: "Introductory measurement" },
];
