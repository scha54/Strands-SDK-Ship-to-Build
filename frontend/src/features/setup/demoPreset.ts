// Demo_Mode preset values for the setup form.
//
// R-01.5: selecting the Demo_Mode preset fills Age_Band, Subject and Objects
// with preset values while keeping every field editable before submission.
// Per the design, the preset is Age_Band 6-8, mathematics (the
// `arithmetic_counting` Subject) and exactly seven Objects: five stones and two
// leaves (R-12.1). The backend seed file is the single source of truth; these
// values mirror it so the form can be pre-filled without a round trip. The
// seven Objects are the seed names verbatim. They must stay distinct under the backend
// normalizer (case-insensitive dedupe), so each stone and leaf is numbered; a test reads the
// seed file and fails on any drift.
import type { AgeBand, Subject } from "../../api/types";

export interface DemoPreset {
  readonly ageBand: AgeBand;
  readonly subject: Subject;
  /** Raw object lines exactly as a Facilitator would type them. */
  readonly objects: readonly string[];
}

export const DEMO_PRESET: DemoPreset = {
  ageBand: "6-8",
  subject: "arithmetic_counting",
  objects: ["Stone 1", "Stone 2", "Stone 3", "Stone 4", "Stone 5", "Leaf 1", "Leaf 2"],
};

/** The preset Objects rendered as the multi-line text the Objects field holds. */
export const DEMO_PRESET_OBJECTS_TEXT: string = DEMO_PRESET.objects.join("\n");
