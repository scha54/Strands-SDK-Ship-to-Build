import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import type {
  LearnerView,
  LearningLoopApi,
  LearningSummary,
} from "../api/learning";
import { AppLayout } from "../app/AppLayout";
import { SupervisionNotice } from "../components/SupervisionNotice";
import { LearningSession } from "../features/session/LearningSession";
import { SetupForm } from "../features/setup/SetupForm";
import { SummaryView } from "../features/summary/SummaryView";
import { Timeline } from "../features/timeline/Timeline";
import { LiveApp } from "./LiveApp";

/**
 * Screen gallery used only by the Playwright accessibility runs (R-09.1 to
 * R-09.5, R-09.8, R-09.10; NFR-03, NFR-04). Select a screen with `?screen=`.
 * It renders the real feature components against a canned in-memory API, so no
 * backend is needed. It is not part of the production build (not an entry in
 * index.html).
 */

const params = new URLSearchParams(window.location.search);
const screen = params.get("screen") ?? "setup";

const view = (access: "standard" | "alt" | "none"): LearnerView => ({
  session_id: "demo",
  title: "Count the stones",
  setup: "Gather your stones.",
  source: "generated",
  progress: { current: 1, total: 3, label: "1 of 3" },
  activity: {
    id: "a1",
    instruction: "Sort the red stones from the blue stones, then count the red ones.",
    required_objects: ["stones"],
    answer_kind: "integer",
    difficulty: 1,
    answered: false,
    access:
      access === "standard"
        ? null
        : {
            needs: ["color"],
            alternatives:
              access === "alt"
                ? { color: "Sort the big stones from the small stones, then count the big ones." }
                : {},
          },
  },
});

const summary: LearningSummary = {
  concepts_practiced: ["Counting to 10"],
  next_steps: ["Try counting leaves."],
  provisional_estimate: "provisional: practising",
} as LearningSummary;

function api(access: "standard" | "alt" | "none"): LearningLoopApi {
  const v = view(access);
  return {
    getBaseline: async () => ({
      question_id: "b",
      topic: "counting",
      prompt: "How sure are you at counting? (1 to 5)",
      scale_max: 5,
      can_skip: true,
    }),
    postBaseline: async () => ({ state: "active", view: v }),
    getLearnerView: async () => v,
    postAnswer: async () => {
      throw new Error("unused");
    },
    postHint: async () => ({
      activity_id: "a1",
      hint: "Count slowly.",
      hints_used: 1,
      activity_status: "pending",
    }),
    postAdvance: async () => ({ state: "active", finished: false, view: v }),
    getEndCheck: async () => {
      throw new Error("unused");
    },
    postEndCheck: async () => ({ state: "completed", summary }),
    getSummary: async () => summary,
    stop: async () => undefined,
    end: async () => undefined,
    remove: async () => undefined,
  };
}

// eslint-disable-next-line react-refresh/only-export-components -- entry file, no exports
function Screen(): React.JSX.Element {
  switch (screen) {
    case "live":
      return <LiveApp backend={params.get("backend") === "fail" ? "fail" : "ok"} />;
    case "timeline":
      return (
        <Timeline
          source="live"
          events={[
            { stage: "understand_objects", status: "completed" },
            { stage: "choose_objective", status: "started" },
          ]}
        />
      );
    case "summary":
      return (
        <>
          <SupervisionNotice />
          <SummaryView summary={summary} />
        </>
      );
    case "activity":
      return <LearningSession api={api("standard")} onDeleted={() => undefined} />;
    case "activity-alt":
      return <LearningSession api={api("alt")} onDeleted={() => undefined} />;
    case "activity-none":
      return <LearningSession api={api("none")} onDeleted={() => undefined} />;
    default:
      return (
        <>
          <h1>The Invisible Classroom</h1>
          <SetupForm onSubmit={async () => undefined} />
        </>
      );
  }
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AppLayout>
      {screen !== "setup" && <h1>The Invisible Classroom</h1>}
      <Screen />
    </AppLayout>
  </StrictMode>,
);
