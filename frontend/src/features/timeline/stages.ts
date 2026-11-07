import type { AgentStageEvent } from "../../api/types";

/** Label required on every stage screen when running on seed data (R-12.4). */
export const DEMO_FALLBACK_LABEL = "Demo fallback \u2014 no live agent execution";

/** The five sanitized stages in display order (R-12.2). */
export const STAGES = [
  { id: "understand_objects", title: "Understand objects" },
  { id: "choose_objective", title: "Choose objective" },
  { id: "create_story", title: "Create story" },
  { id: "assess_answer", title: "Assess answer" },
  { id: "adapt_next_activity", title: "Adapt next activity" },
] as const;

export type StageId = (typeof STAGES)[number]["id"];
export type StageState = "pending" | "in_progress" | "complete" | "failed";
export type ExecutionSource = "live" | "demo_fallback";

export interface StageView {
  id: StageId;
  title: string;
  state: StageState;
}

/**
 * Reduce raw Stage_Events to the five display stages. Only the stage id and
 * status are read; specialists, versions, timestamps and any other fields are
 * never surfaced (R-12.3).
 */
export function deriveStages(
  events: ReadonlyArray<Pick<AgentStageEvent, "stage" | "status">>,
): StageView[] {
  const latest = new Map<string, AgentStageEvent["status"]>();
  for (const e of events) latest.set(e.stage, e.status);
  return STAGES.map(({ id, title }) => {
    const status = latest.get(id);
    const state: StageState =
      status === "completed"
        ? "complete"
        : status === "started"
          ? "in_progress"
          : status === "failed"
            ? "failed"
            : "pending";
    return { id, title, state };
  });
}
