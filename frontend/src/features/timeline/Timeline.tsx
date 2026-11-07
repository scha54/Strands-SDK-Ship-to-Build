import { SupervisionNotice } from "../../components/SupervisionNotice";
import type { AgentStageEvent } from "../../api/types";
import {
  DEMO_FALLBACK_LABEL,
  deriveStages,
  type ExecutionSource,
  type StageState,
} from "./stages";
import "./Timeline.css";

/**
 * Five-stage timeline (R-12.2). Shows only sanitized stage titles and states;
 * prompts, reasoning, credentials and internal identifiers are never rendered
 * (R-12.3). In fallback the label is shown on every stage (R-12.4) and live
 * versus fallback execution is always distinguishable (G5).
 */

export interface TimelineProps {
  events: ReadonlyArray<Pick<AgentStageEvent, "stage" | "status">>;
  source: ExecutionSource;
}

const STATE_TEXT: Record<StageState, string> = {
  pending: "Pending",
  in_progress: "In progress",
  complete: "Complete",
  failed: "Failed",
};

const STATE_ICON: Record<StageState, string> = {
  pending: "\u25CB",
  in_progress: "\u25D0",
  complete: "\u2713",
  failed: "\u2715",
};

export function Timeline({ events, source }: TimelineProps): React.JSX.Element {
  const stages = deriveStages(events);
  const fallback = source === "demo_fallback";

  return (
    <section
      className="ic-timeline ic-stack"
      aria-labelledby="ic-timeline-heading"
      data-testid="timeline"
      data-source={source}
    >
      <h2 id="ic-timeline-heading">How the lesson was made</h2>
      <p
        className={`ic-timeline__mode ic-timeline__mode--${fallback ? "fallback" : "live"}`}
        data-testid="timeline-mode"
      >
        {fallback ? DEMO_FALLBACK_LABEL : "Live agent execution"}
      </p>
      <SupervisionNotice />
      <ol className="ic-timeline__list" aria-label="Lesson creation stages">
        {stages.map((s, i) => (
          <li
            key={s.id}
            className={`ic-timeline__stage ic-timeline__stage--${s.state}`}
            data-testid={`stage-${s.id}`}
            data-state={s.state}
            aria-current={s.state === "in_progress" ? "step" : undefined}
          >
            <span className="ic-timeline__icon" aria-hidden="true">
              {STATE_ICON[s.state]}
            </span>
            <div>
              <h3 className="ic-timeline__title">
                Step {i + 1}: {s.title}
              </h3>
              <p className="ic-timeline__state">{STATE_TEXT[s.state]}</p>
              {fallback && (
                <p
                  className="ic-timeline__fallback"
                  data-testid={`stage-fallback-${s.id}`}
                >
                  {DEMO_FALLBACK_LABEL}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default Timeline;
