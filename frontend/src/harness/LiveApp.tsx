import { useEffect, useMemo, useState } from "react";

import { ApiClient } from "../api/client";
import { LearningApi } from "../api/learning";
import type { AgentStageEvent, CreateSessionRequest } from "../api/types";
import { LearningSession } from "../features/session/LearningSession";
import { SetupForm } from "../features/setup/SetupForm";
import { Timeline } from "../features/timeline/Timeline";

/**
 * Real-backend screen used only by the Playwright end-to-end runs (task 10.4;
 * R-12.2, R-12.6; NFR-05, NFR-09). It wires the real setup form, five-stage
 * timeline and learning loop to a stub-backed API through the Vite dev-server
 * proxy (`/e2e-ok` or `/e2e-fail`). It is not part of the production build.
 */

interface EventsView {
  state: string;
  events: AgentStageEvent[];
  lesson_source?: string | null;
  label?: string | null;
  error_code?: string | null;
  options?: string[];
}

type Phase =
  | { name: "setup" }
  | { name: "generating" }
  | { name: "failed"; code: string; options: string[] }
  | { name: "ready" }
  | { name: "deleted" };

interface Created {
  session_id: string;
  capability_token: string;
}

declare global {
  interface Window {
    __e2e?: { sessionId: string; token: string };
  }
}

const POLL_MS = 100;
const MAX_POLLS = 200;

export function LiveApp({ backend }: { backend: "ok" | "fail" }): React.JSX.Element {
  const anonymous = useMemo(() => new ApiClient({ baseUrl: `/e2e-${backend}/api/v1` }), [backend]);
  const [client, setClient] = useState<ApiClient | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ name: "setup" });
  const [events, setEvents] = useState<AgentStageEvent[]>([]);
  const [attempt, setAttempt] = useState(0);

  const startGeneration = async (
    authed: ApiClient,
    id: string,
    mode: "generate" | "safe_template",
  ): Promise<void> => {
    await authed.request(`/sessions/${id}/lessons`, {
      method: "POST",
      body: { mode },
      idempotencyKey: globalThis.crypto.randomUUID(),
    });
    setPhase({ name: "generating" });
    setAttempt((n) => n + 1);
  };

  const onStart = async (request: CreateSessionRequest): Promise<void> => {
    const created = await anonymous.request<Created>("/sessions", {
      method: "POST",
      body: request,
    });
    const authed = anonymous.withToken(created.capability_token);
    window.__e2e = { sessionId: created.session_id, token: created.capability_token };
    setClient(authed);
    setSessionId(created.session_id);
    await startGeneration(authed, created.session_id, "generate");
  };

  // Poll the sanitized stage events until the Lesson is ready or generation fails (R-04.5).
  useEffect(() => {
    if (phase.name !== "generating" || !client || !sessionId) return;
    let cancelled = false;
    void (async () => {
      for (let i = 0; i < MAX_POLLS && !cancelled; i++) {
        const view = await client.request<EventsView>(`/sessions/${sessionId}/events`);
        if (cancelled) return;
        setEvents(view.events);
        if (view.state === "ready") return setPhase({ name: "ready" });
        if (view.state === "failed") {
          return setPhase({
            name: "failed",
            code: view.error_code ?? "generation_failed",
            options: view.options ?? [],
          });
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [phase.name, client, sessionId, attempt]);

  const learning = useMemo(
    () => (client && sessionId ? new LearningApi(client, sessionId) : null),
    [client, sessionId],
  );

  return (
    <div data-testid="live-app" data-session-id={sessionId ?? ""}>
      {phase.name === "setup" && <SetupForm onSubmit={onStart} />}

      {(phase.name === "generating" || phase.name === "ready") && (
        <Timeline events={events} source="live" />
      )}

      {phase.name === "failed" && client && sessionId && (
        <div role="alert" data-testid="generation-failed">
          <p>We couldn&apos;t make the lesson ({phase.code}). Your choices are kept.</p>
          {phase.options.includes("retry") && (
            <button type="button" onClick={() => void startGeneration(client, sessionId, "generate")}>
              Try again
            </button>
          )}
          {phase.options.includes("safe_template") && (
            <button
              type="button"
              onClick={() => void startGeneration(client, sessionId, "safe_template")}
            >
              Use a safe template
            </button>
          )}
        </div>
      )}

      {phase.name === "ready" && learning && (
        <LearningSession api={learning} onDeleted={() => setPhase({ name: "deleted" })} />
      )}

      {phase.name === "deleted" && <p role="status">This session was deleted.</p>}
    </div>
  );
}
