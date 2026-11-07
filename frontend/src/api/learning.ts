// Typed wrappers over the learning-loop and session-control routes.
//
// Request/response shapes mirror the backend's learning-loop models (R-05.x,
// R-07.x, R-08.3, R-10.4, R-10.9). The generated OpenAPI file does not yet
// expose route paths, so the route payloads are declared here next to the
// client; shared schemas (SessionSummary, AssessmentStatus) come from the
// generated types.
import type { ApiClient } from "./client";
import type { AssessmentStatus, SessionSummary } from "./types";

export interface Progress {
  current: number;
  total: number;
  label: string;
}

export interface LearnerActivity {
  id: string;
  instruction: string;
  required_objects: string[];
  answer_kind: string;
  difficulty: number;
  answered: boolean;
  expected_answer?: string | null;
  rubric?: string | null;
}

export interface LearnerView {
  session_id: string;
  title: string;
  setup: string;
  source: string;
  activity: LearnerActivity | null;
  progress: Progress;
}

export interface QuestionView {
  question_id: string;
  topic: string;
  prompt: string;
  scale_max: number;
  can_skip: boolean;
}

export interface QuestionAnswer {
  answer: number | null;
  skipped: boolean;
}

export interface QuestionResult {
  state: string;
  view?: LearnerView | null;
  summary?: LearningSummary | null;
}

export interface AnswerResult {
  activity_id: string;
  status: AssessmentStatus;
  explanation: string;
  clarification_requested: boolean;
  clarification_prompt?: string | null;
  offer_skip_or_hint: boolean;
  excluded_from_mastery: boolean;
  adjustment_note?: string | null;
  replayed: boolean;
  view: LearnerView;
}

export interface HintResult {
  activity_id: string;
  hint: string;
  hints_used: number;
  activity_status: "pending" | "completed" | "skipped";
}

export interface AdvanceResult {
  state: string;
  finished: boolean;
  view: LearnerView;
}

/** Summary payload; the skipped flags are optional so older servers still parse. */
export type LearningSummary = SessionSummary & {
  baseline_skipped?: boolean;
  end_skipped?: boolean;
};

/** Operations the learning-loop UI needs. Implemented by {@link LearningApi}. */
export interface LearningLoopApi {
  getBaseline(signal?: AbortSignal): Promise<QuestionView>;
  postBaseline(body: QuestionAnswer, signal?: AbortSignal): Promise<QuestionResult>;
  getLearnerView(signal?: AbortSignal): Promise<LearnerView>;
  postAnswer(
    answer: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AnswerResult>;
  postHint(signal?: AbortSignal): Promise<HintResult>;
  postAdvance(
    activityId: string,
    outcome: "completed" | "skipped",
    signal?: AbortSignal,
  ): Promise<AdvanceResult>;
  getEndCheck(signal?: AbortSignal): Promise<QuestionView>;
  postEndCheck(body: QuestionAnswer, signal?: AbortSignal): Promise<QuestionResult>;
  getSummary(signal?: AbortSignal): Promise<LearningSummary>;
  stop(signal?: AbortSignal): Promise<void>;
  end(signal?: AbortSignal): Promise<void>;
  remove(signal?: AbortSignal): Promise<void>;
}

/** Concrete implementation backed by the shared {@link ApiClient}. */
export class LearningApi implements LearningLoopApi {
  private readonly base: string;

  constructor(
    private readonly client: ApiClient,
    sessionId: string,
  ) {
    this.base = `/sessions/${encodeURIComponent(sessionId)}`;
  }

  getBaseline(signal?: AbortSignal) {
    return this.client.request<QuestionView>(`${this.base}/baseline`, { signal });
  }
  postBaseline(body: QuestionAnswer, signal?: AbortSignal) {
    return this.client.request<QuestionResult>(`${this.base}/baseline`, {
      method: "POST",
      body,
      signal,
    });
  }
  getLearnerView(signal?: AbortSignal) {
    return this.client.request<LearnerView>(`${this.base}/learner-view`, { signal });
  }
  postAnswer(answer: string, idempotencyKey: string, signal?: AbortSignal) {
    return this.client.request<AnswerResult>(`${this.base}/answers`, {
      method: "POST",
      body: { answer },
      idempotencyKey,
      signal,
    });
  }
  postHint(signal?: AbortSignal) {
    return this.client.request<HintResult>(`${this.base}/hint`, {
      method: "POST",
      signal,
    });
  }
  postAdvance(
    activityId: string,
    outcome: "completed" | "skipped",
    signal?: AbortSignal,
  ) {
    return this.client.request<AdvanceResult>(`${this.base}/advance`, {
      method: "POST",
      body: { activity_id: activityId, outcome },
      signal,
    });
  }
  getEndCheck(signal?: AbortSignal) {
    return this.client.request<QuestionView>(`${this.base}/end-check`, { signal });
  }
  postEndCheck(body: QuestionAnswer, signal?: AbortSignal) {
    return this.client.request<QuestionResult>(`${this.base}/end-check`, {
      method: "POST",
      body,
      signal,
    });
  }
  getSummary(signal?: AbortSignal) {
    return this.client.request<LearningSummary>(`${this.base}/summary`, { signal });
  }
  async stop(signal?: AbortSignal) {
    await this.client.request<unknown>(`${this.base}/stop`, { method: "POST", signal });
  }
  async end(signal?: AbortSignal) {
    await this.client.request<unknown>(`${this.base}/end`, { method: "POST", signal });
  }
  async remove(signal?: AbortSignal) {
    await this.client.request<unknown>(this.base, { method: "DELETE", signal });
  }
}
