import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError } from "../../api/client";
import type {
  AnswerResult,
  LearnerView,
  LearningLoopApi,
  LearningSummary,
  QuestionView,
} from "../../api/learning";
import { SupervisionNotice } from "../../components/SupervisionNotice";
import { ActivityView } from "../activity/ActivityView";
import { BaselineScreen } from "../baseline/BaselineScreen";
import { EndCheckScreen } from "../baseline/EndCheckScreen";
import { SummaryView } from "../summary/SummaryView";
import { SessionControls } from "./SessionControls";

/** A failed or stalled save must be reported within this many ms (R-10.9). */
export const SAVE_DEADLINE_MS = 2000;

type Phase =
  | { name: "loading" }
  | { name: "baseline"; question: QuestionView }
  | { name: "activity"; view: LearnerView }
  | { name: "endcheck"; question: QuestionView }
  | { name: "summary"; summary: LearningSummary }
  | { name: "stopped" };

export interface LearningSessionProps {
  api: LearningLoopApi;
  /** Called after the session has been deleted on the server. */
  onDeleted: () => void;
}

function newKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * Drives the learning loop: baseline, Activities, end check and summary.
 *
 * Every write goes through `run`, which aborts after SAVE_DEADLINE_MS and shows
 * a save-failure message with Retry while leaving the on-screen state untouched
 * (R-10.9). The supervision notice is rendered on every Lesson screen (R-08.4).
 */
export function LearningSession({
  api,
  onDeleted,
}: LearningSessionProps): React.JSX.Element {
  const [phase, setPhase] = useState<Phase>({ name: "loading" });
  const [busy, setBusy] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [ended, setEnded] = useState(false);
  const lastAction = useRef<((signal: AbortSignal) => Promise<void>) | null>(null);
  const answerKey = useRef<{ text: string; key: string } | null>(null);

  const run = useCallback(
    async (action: (signal: AbortSignal) => Promise<void>): Promise<void> => {
      lastAction.current = action;
      setSaveFailed(false);
      setBusy(true);
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), SAVE_DEADLINE_MS);
      try {
        await action(controller.signal);
      } catch (error) {
        if (error instanceof ApiRequestError && error.body?.code === "session_stopped") {
          setPhase({ name: "stopped" });
        } else {
          setSaveFailed(true);
        }
      } finally {
        clearTimeout(timer);
        setBusy(false);
      }
    },
    [],
  );

  // The baseline is always the first thing shown (R-07.1).
  useEffect(() => {
    void run(async (signal) => {
      const question = await api.getBaseline(signal);
      setPhase({ name: "baseline", question });
    });
  }, [api, run]);

  const enterActivity = (view: LearnerView): void => {
    setResult(null);
    setHint(null);
    answerKey.current = null;
    setPhase({ name: "activity", view });
  };

  const submitBaseline = (answer: number | null): void => {
    void run(async (signal) => {
      const res = await api.postBaseline(
        { answer, skipped: answer === null },
        signal,
      );
      enterActivity(res.view ?? (await api.getLearnerView(signal)));
    });
  };

  const submitEndCheck = (answer: number | null): void => {
    void run(async (signal) => {
      const res = await api.postEndCheck({ answer, skipped: answer === null }, signal);
      const summary = res.summary ?? (await api.getSummary(signal));
      setPhase({ name: "summary", summary });
    });
  };

  const submitAnswer = (text: string): void => {
    // Reuse the idempotency key for identical retries so a save is applied once.
    if (answerKey.current?.text !== text) answerKey.current = { text, key: newKey() };
    const key = answerKey.current.key;
    void run(async (signal) => {
      const res = await api.postAnswer(text, key, signal);
      setResult(res);
      setPhase((p) => (p.name === "activity" ? { name: "activity", view: res.view } : p));
    });
  };

  const requestHint = (): void => {
    void run(async (signal) => {
      const res = await api.postHint(signal);
      setHint(res.hint);
    });
  };

  const advance = (outcome: "completed" | "skipped"): void => {
    if (phase.name !== "activity" || phase.view.activity === null) return;
    const activityId = phase.view.activity.id;
    void run(async (signal) => {
      const res = await api.postAdvance(activityId, outcome, signal);
      if (res.finished) {
        const question = await api.getEndCheck(signal);
        setPhase({ name: "endcheck", question });
      } else {
        enterActivity(res.view);
      }
    });
  };

  const stop = (): void => {
    void run(async (signal) => {
      await api.stop(signal);
      setPhase({ name: "stopped" });
    });
  };

  const end = (): void => {
    void run(async (signal) => {
      await api.end(signal);
      setEnded(true);
      setPhase({ name: "summary", summary: await api.getSummary(signal) });
    });
  };

  const remove = (): void => {
    void run(async (signal) => {
      await api.remove(signal);
      onDeleted();
    });
  };

  const stopped = phase.name === "stopped";

  return (
    <div className="ic-learning">
      <SupervisionNotice />

      {phase.name === "loading" && !saveFailed && <p>Loading…</p>}

      {phase.name === "baseline" && (
        <BaselineScreen question={phase.question} busy={busy} onSubmit={submitBaseline} />
      )}
      {phase.name === "activity" && (
        <ActivityView
          key={phase.view.activity?.id ?? "done"}
          view={phase.view}
          result={result}
          hint={hint}
          busy={busy}
          onSubmitAnswer={submitAnswer}
          onHint={requestHint}
          onAdvance={advance}
        />
      )}
      {phase.name === "endcheck" && (
        <EndCheckScreen
          question={phase.question}
          busy={busy}
          onSubmit={submitEndCheck}
        />
      )}
      {phase.name === "summary" && <SummaryView summary={phase.summary} />}
      {stopped && (
        <section aria-labelledby="stopped-heading" className="ic-learning-screen">
          <h2 id="stopped-heading">Session stopped</h2>
          <p>
            This session has stopped. Nothing more will be saved. You can delete
            it now.
          </p>
        </section>
      )}

      {saveFailed && (
        <div role="alert" data-testid="save-error">
          <p>We couldn&apos;t save that. Your work is still here.</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              const action = lastAction.current;
              if (action) void run(action);
            }}
          >
            Try again
          </button>
        </div>
      )}

      <SessionControls
        stopped={stopped}
        ended={ended || phase.name === "summary"}
        busy={busy}
        onStop={stop}
        onEnd={end}
        onDelete={remove}
      />
    </div>
  );
}
