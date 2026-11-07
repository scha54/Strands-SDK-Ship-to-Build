// Component tests for the learning-loop UI.
//
// Validates: R-07.1 (baseline first), R-07.6 / R-05.7 (skipped baseline continues
// without data loss), R-05.1 (one Activity, "n of N"), R-05.6 / R-05.8 (hint,
// advance, summary), R-06.3 (clarification prompt), R-07.2 (end check),
// R-07.3 to R-07.5 (observed difference rules), R-08.3 / R-10.4 (Stop, End,
// Delete), R-08.4 (supervision notice on every Lesson screen), R-09.7 / NFR-09
// (no timed input), R-10.9 (save-failure message within 2 s with retry and
// retained state), NFR-03 (labelled controls).
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../api/client";
import type {
  AnswerResult,
  LearnerView,
  LearningLoopApi,
  LearningSummary,
} from "../../api/learning";
import { SummaryView } from "../summary/SummaryView";
import { LearningSession, SAVE_DEADLINE_MS } from "./LearningSession";

function view(n: number, total = 2, answered = false): LearnerView {
  return {
    session_id: "s1",
    title: "Stone Counting",
    setup: "setup",
    source: "generated",
    activity: {
      id: `a${n}`,
      instruction: `Count the stones, step ${n}.`,
      required_objects: ["stone"],
      answer_kind: "integer",
      difficulty: 1,
      answered,
      expected_answer: answered ? "5" : null,
      rubric: answered ? "Counts all five." : null,
    },
    progress: { current: n, total, label: `${n} of ${total}` },
  };
}

function answerResult(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    activity_id: "a1",
    status: "correct",
    explanation: "Nice counting.",
    clarification_requested: false,
    offer_skip_or_hint: false,
    excluded_from_mastery: false,
    replayed: false,
    view: view(1, 2, true),
    ...overrides,
  };
}

const SUMMARY: LearningSummary = {
  concepts_practiced: ["counting"],
  next_steps: ["Try again"],
  baseline: null,
  end_answer: null,
  difference: null,
  provisional_estimate: null,
  warning: null,
};

function makeApi(overrides: Partial<LearningLoopApi> = {}): LearningLoopApi {
  const question = {
    question_id: "q1",
    topic: "counting",
    prompt: "How sure are you at counting?",
    scale_max: 5,
    can_skip: true,
  };
  return {
    getBaseline: vi.fn().mockResolvedValue(question),
    postBaseline: vi.fn().mockResolvedValue({ state: "ACTIVE", view: view(1) }),
    getLearnerView: vi.fn().mockResolvedValue(view(1)),
    postAnswer: vi.fn().mockResolvedValue(answerResult()),
    postHint: vi.fn().mockResolvedValue({
      activity_id: "a1",
      hint: "Touch each stone once.",
      hints_used: 1,
      activity_status: "pending",
    }),
    postAdvance: vi.fn().mockResolvedValue({ state: "ACTIVE", finished: false, view: view(2) }),
    getEndCheck: vi.fn().mockResolvedValue({ ...question, question_id: "q2" }),
    postEndCheck: vi.fn().mockResolvedValue({ state: "COMPLETED", summary: SUMMARY }),
    getSummary: vi.fn().mockResolvedValue(SUMMARY),
    stop: vi.fn().mockResolvedValue(undefined),
    end: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function renderSession(api: LearningLoopApi, onDeleted = vi.fn()) {
  render(<LearningSession api={api} onDeleted={onDeleted} />);
  return { onDeleted };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("baseline screen (R-07.1, R-07.6, R-05.7)", () => {
  it("shows the baseline first with the supervision notice and answer/skip", async () => {
    renderSession(makeApi());

    expect(await screen.findByText("How sure are you at counting?")).toBeInTheDocument();
    expect(screen.getByTestId("supervision-notice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit answer/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /skip this question/i })).toBeEnabled();
    expect(screen.queryByTestId("progress")).not.toBeInTheDocument();
  });

  it("continues to the first Activity after a skipped baseline without data loss", async () => {
    const api = makeApi();
    renderSession(api);

    fireEvent.click(await screen.findByRole("button", { name: /skip this question/i }));

    expect(await screen.findByTestId("progress")).toHaveTextContent("1 of 2");
    expect(api.postBaseline).toHaveBeenCalledWith(
      { answer: null, skipped: true },
      expect.anything(),
    );
    expect(screen.queryByTestId("save-error")).not.toBeInTheDocument();
    expect(screen.getByText("Count the stones, step 1.")).toBeInTheDocument();
  });

  it("sends the chosen number when answered", async () => {
    const api = makeApi();
    renderSession(api);

    fireEvent.click(await screen.findByRole("radio", { name: "3" }));
    fireEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    await screen.findByTestId("progress");
    expect(api.postBaseline).toHaveBeenCalledWith(
      { answer: 3, skipped: false },
      expect.anything(),
    );
  });
});

describe("Activity view (R-05.1, R-05.6, R-06.3, R-08.4)", () => {
  async function toActivity(api: LearningLoopApi): Promise<void> {
    renderSession(api);
    fireEvent.click(await screen.findByRole("button", { name: /skip this question/i }));
    await screen.findByTestId("progress");
  }

  it("shows one Activity with n of N, the notice, and no answer before submitting", async () => {
    await toActivity(makeApi());

    expect(screen.getByTestId("progress")).toHaveTextContent("1 of 2");
    expect(screen.getAllByText(/Count the stones/)).toHaveLength(1);
    expect(screen.getByTestId("supervision-notice")).toBeInTheDocument();
    expect(screen.queryByTestId("expected-answer")).not.toBeInTheDocument();
  });

  it("shows a hint when requested", async () => {
    await toActivity(makeApi());

    fireEvent.click(screen.getByRole("button", { name: /show a hint/i }));

    expect(await screen.findByTestId("hint")).toHaveTextContent("Touch each stone once.");
  });

  it("shows feedback and the expected answer, then advances to the next Activity", async () => {
    const api = makeApi();
    await toActivity(api);

    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /check my answer/i }));

    expect(await screen.findByText("Nice counting.")).toBeInTheDocument();
    expect(screen.getByTestId("expected-answer")).toHaveTextContent("5");

    fireEvent.click(screen.getByRole("button", { name: /^next$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("progress")).toHaveTextContent("2 of 2"),
    );
    expect(api.postAdvance).toHaveBeenCalledWith("a1", "completed", expect.anything());
  });

  it("shows a clarification prompt and keeps the answer box usable", async () => {
    const api = makeApi({
      postAnswer: vi.fn().mockResolvedValue(
        answerResult({
          status: "unassessable",
          explanation: "I could not tell.",
          clarification_requested: true,
          clarification_prompt: "Can you say how many stones?",
        }),
      ),
    });
    await toActivity(api);

    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "hmm" } });
    fireEvent.click(screen.getByRole("button", { name: /check my answer/i }));

    expect(await screen.findByTestId("clarification")).toHaveTextContent(
      "Can you say how many stones?",
    );
    expect(screen.queryByRole("button", { name: /^next$/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your answer")).toHaveValue("hmm");
  });

  it("does not call the API for an empty answer", async () => {
    const api = makeApi();
    await toActivity(api);

    fireEvent.click(screen.getByRole("button", { name: /check my answer/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(/type an answer/i);
    expect(api.postAnswer).not.toHaveBeenCalled();
  });

  it("goes to the end check and then the summary after the last Activity", async () => {
    const api = makeApi({
      postAdvance: vi.fn().mockResolvedValue({
        state: "ACTIVE",
        finished: true,
        view: { ...view(2), activity: null },
      }),
    });
    await toActivity(api);

    fireEvent.click(screen.getByRole("button", { name: /skip this activity/i }));
    expect(await screen.findByText("One last check")).toBeInTheDocument();
    expect(screen.getByTestId("supervision-notice")).toBeInTheDocument();
    expect(api.postAdvance).toHaveBeenCalledWith("a1", "skipped", expect.anything());

    fireEvent.click(screen.getByRole("radio", { name: "4" }));
    fireEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(await screen.findByText("Session summary")).toBeInTheDocument();
    expect(screen.getByTestId("supervision-notice")).toBeInTheDocument();
  });
});

describe("no timed input (R-09.7, NFR-09)", () => {
  it("never times out or submits an unanswered Activity, however long the Learner waits", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    const api = makeApi();
    renderSession(api);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("button", { name: /skip this question/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "4" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000);
    });

    expect(screen.getByLabelText("Your answer")).toHaveValue("4");
    expect(api.postAnswer).not.toHaveBeenCalled();
    expect(api.postAdvance).not.toHaveBeenCalled();
    expect(screen.queryByTestId("save-error")).not.toBeInTheDocument();
    expect(screen.queryByText(/time left|seconds left|hurry/i)).not.toBeInTheDocument();
  });
});

describe("save failure (R-10.9)", () => {
  it("shows a failure message at once on error, retains the answer, and retries with the same key", async () => {
    const postAnswer = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(answerResult());
    const api = makeApi({ postAnswer });
    renderSession(api);
    fireEvent.click(await screen.findByRole("button", { name: /skip this question/i }));
    await screen.findByTestId("progress");

    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /check my answer/i }));

    expect(await screen.findByTestId("save-error")).toHaveTextContent(/couldn't save/i);
    expect(screen.getByLabelText("Your answer")).toHaveValue("5");
    expect(screen.getByTestId("progress")).toHaveTextContent("1 of 2");

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Nice counting.")).toBeInTheDocument();
    expect(screen.queryByTestId("save-error")).not.toBeInTheDocument();
    expect(postAnswer).toHaveBeenCalledTimes(2);
    expect(postAnswer.mock.calls[1]?.[1]).toBe(postAnswer.mock.calls[0]?.[1]);
  });

  it("reports a stalled save within 2 s and keeps the selection for retry", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    const postBaseline = vi
      .fn()
      .mockImplementationOnce(
        (_body: unknown, signal: AbortSignal) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(new Error("aborted")));
          }),
      )
      .mockResolvedValueOnce({ state: "ACTIVE", view: view(1) });
    renderSession(makeApi({ postBaseline }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    fireEvent.click(screen.getByRole("radio", { name: "2" }));
    fireEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_DEADLINE_MS);
    });

    expect(screen.getByTestId("save-error")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "2" })).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("progress")).toHaveTextContent("1 of 2");
  });

  it("keeps the current Activity when advance fails and allows retry", async () => {
    const postAdvance = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce({ state: "ACTIVE", finished: false, view: view(2) });
    renderSession(makeApi({ postAdvance }));
    fireEvent.click(await screen.findByRole("button", { name: /skip this question/i }));
    await screen.findByTestId("progress");

    fireEvent.click(screen.getByRole("button", { name: /skip this activity/i }));
    expect(await screen.findByTestId("save-error")).toBeInTheDocument();
    expect(screen.getByTestId("progress")).toHaveTextContent("1 of 2");

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(screen.getByTestId("progress")).toHaveTextContent("2 of 2"),
    );
  });
});

describe("Stop, End and Delete controls (R-08.3, R-10.4)", () => {
  it("Stop calls the API and shows the stopped state without Stop/End", async () => {
    const api = makeApi();
    renderSession(api);
    await screen.findByText("How sure are you at counting?");

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByText("Session stopped")).toBeInTheDocument();
    expect(api.stop).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete session/i })).toBeInTheDocument();
  });

  it("shows the stopped state when a write is rejected with session_stopped", async () => {
    const err = new ApiRequestError(409, "stopped", {
      code: "session_stopped",
      message: "stopped",
      correlation_id: "c",
      details: null,
    });
    renderSession(makeApi({ postBaseline: vi.fn().mockRejectedValue(err) }));

    fireEvent.click(await screen.findByRole("button", { name: /skip this question/i }));

    expect(await screen.findByText("Session stopped")).toBeInTheDocument();
    expect(screen.queryByTestId("save-error")).not.toBeInTheDocument();
  });

  it("End shows the summary", async () => {
    const api = makeApi();
    renderSession(api);
    await screen.findByText("How sure are you at counting?");

    fireEvent.click(screen.getByRole("button", { name: /end session/i }));

    expect(await screen.findByText("Session summary")).toBeInTheDocument();
    expect(api.end).toHaveBeenCalledTimes(1);
  });

  it("Delete asks for confirmation before calling the API", async () => {
    const api = makeApi();
    const { onDeleted } = renderSession(api);
    await screen.findByText("How sure are you at counting?");

    fireEvent.click(screen.getByRole("button", { name: /delete session/i }));
    expect(api.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /yes, delete/i }));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(api.remove).toHaveBeenCalledTimes(1);
  });
});

describe("summary difference rule (R-05.8, R-07.3, R-07.4, R-07.5, R-06.6)", () => {
  const base: LearningSummary = { ...SUMMARY, provisional_estimate: "provisional: secure" };

  it("shows concepts, next steps and the provisional estimate", () => {
    render(<SummaryView summary={base} />);

    expect(screen.getByText("counting")).toBeInTheDocument();
    expect(screen.getByText("Try again")).toBeInTheDocument();
    expect(screen.getByTestId("provisional")).toHaveTextContent(/provisional/i);
    expect(screen.queryByTestId("difference")).not.toBeInTheDocument();
  });

  it("shows the difference with the not-validated warning when both answered", () => {
    render(
      <SummaryView
        summary={{ ...base, baseline: 1, end_answer: 4, difference: 3, warning: null }}
      />,
    );

    expect(screen.getByTestId("difference-value")).toHaveTextContent("3");
    expect(screen.getByTestId("not-validated-warning")).toHaveTextContent(
      /not a validated educational assessment/i,
    );
  });

  it.each([
    ["baseline skipped", { baseline: null, end_answer: 4, baseline_skipped: true }],
    ["end skipped", { baseline: 2, end_answer: null, end_skipped: true }],
    ["both skipped", { baseline: null, end_answer: null, baseline_skipped: true, end_skipped: true }],
  ])("hides the difference and any improvement claim when %s", (_name, extra) => {
    render(<SummaryView summary={{ ...base, ...extra }} />);

    expect(screen.queryByTestId("difference")).not.toBeInTheDocument();
    expect(screen.queryByText(/higher|improv|better|progress/i)).not.toBeInTheDocument();
  });

  it.each([
    ["zero", 3, 3],
    ["negative", 4, 2],
  ])("makes no improvement statement for a %s difference", (_name, b, e) => {
    render(
      <SummaryView
        summary={{ ...base, baseline: b, end_answer: e, difference: e - b }}
      />,
    );

    expect(screen.getByTestId("difference-value")).toHaveTextContent(String(e - b));
    expect(screen.getByTestId("not-validated-warning")).toBeInTheDocument();
    expect(screen.queryByText(/higher|improv|better/i)).not.toBeInTheDocument();
  });
});
