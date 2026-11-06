// Demo_Mode preset values for the setup form.
//
// R-01.5: selecting the Demo_Mode preset fills Age_Band, Subject and Objects
// with preset values while keeping every field editable before submission.
// Per the design, the preset is Age_Band 6-8, mathematics (the
// `arithmetic_counting` Subject) and exactly seven Objects: five stones and two
// leaves (R-12.1). The backend seed file is the single source of truth; these
// values mirror it so the form can be pre-filled without a round trip. The
// seven Objects match the seed exactly (stones and leaves repeated as entered).
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
  objects: ["stone", "stone", "stone", "stone", "stone", "leaf", "leaf"],
};

/** The preset Objects rendered as the multi-line text the Objects field holds. */
export const DEMO_PRESET_OBJECTS_TEXT: string = DEMO_PRESET.objects.join("\n");
