/**
 * Alternative paths for Activities that depend on color, sound or fine motor
 * skills (R-09.8, R-09.10; NFR-03).
 *
 * An Activity may declare which capabilities it `needs` and offer a
 * non-dependent `alternatives` instruction per capability. The Facilitator says
 * which capabilities the Learner cannot use (`avoid`). Resolution is pure and
 * only changes how the Activity is *presented*: the answer, its grading and the
 * completion status are untouched, so equivalent answers always score the same.
 */

export type Capability = "color" | "sound" | "fine_motor";

export const CAPABILITIES: readonly Capability[] = ["color", "sound", "fine_motor"];

export const CAPABILITY_LABELS: Record<Capability, string> = {
  color: "Do not rely on color",
  sound: "Do not rely on sound",
  fine_motor: "Do not rely on fine hand movements",
};

export interface ActivityAccess {
  /** Capabilities the standard version of the Activity depends on. */
  needs: Capability[];
  /** Instruction that completes the Activity without the given capability. */
  alternatives: Partial<Record<Capability, string>>;
}

export type AccessResolution =
  | { kind: "standard" }
  | { kind: "alternative"; instructions: string[] }
  | { kind: "unavailable"; unmet: Capability[] };

/** Decide how an Activity is presented given the capabilities to avoid (R-09.8, R-09.10). */
export function resolveActivityAccess(
  access: ActivityAccess | null | undefined,
  avoid: readonly Capability[],
): AccessResolution {
  if (!access) return { kind: "standard" };
  const blocked = access.needs.filter((c) => avoid.includes(c));
  if (blocked.length === 0) return { kind: "standard" };

  const unmet = blocked.filter((c) => !access.alternatives[c]);
  if (unmet.length > 0) return { kind: "unavailable", unmet };

  const instructions = blocked.map((c) => access.alternatives[c] as string);
  return { kind: "alternative", instructions: [...new Set(instructions)] };
}

export const NO_ALTERNATIVE_MESSAGE =
  "This activity can't be done in the current mode. Your progress is saved.";

export const FACILITATOR_NOTICE_PREFIX =
  "Note for the Facilitator: this activity needs";

export function describeUnmet(unmet: readonly Capability[]): string {
  const words = unmet.map((c) => (c === "fine_motor" ? "fine hand movements" : c));
  return `${FACILITATOR_NOTICE_PREFIX} ${words.join(" and ")}, and no alternative is available. You can skip it or switch the mode.`;
}
