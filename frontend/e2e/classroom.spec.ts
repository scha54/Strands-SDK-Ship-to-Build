/**
 * End-to-end flows against the stub backend (task 10.4).
 *
 * Validates: Requirements R-12.2 (five sanitized stages), R-12.6 (repeatable demo, no live
 * model), R-06.2 (adapted challenge), R-07.1 to R-07.5 (baseline, end check, difference),
 * R-08.3 (Stop), R-10.5 and R-10.6 (delete), R-10.8 (expired session), R-10.9 (save failure
 * keeps on-screen work), R-03.5 (model failure offers retry or Safe_Template), NFR-03, NFR-04,
 * NFR-05, NFR-09, NFR-10.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

interface Handle {
  sessionId: string;
  token: string;
}

async function startDemo(page: Page, backend: "ok" | "fail" = "ok"): Promise<void> {
  await page.goto(`/harness.html?screen=live&backend=${backend}`);
  await page.getByRole("button", { name: "Fill Demo Mode preset" }).click();
  await page.getByRole("button", { name: "Start session" }).click();
}

async function handle(page: Page): Promise<Handle> {
  const value = await page.evaluate(() => window.__e2e);
  if (!value) throw new Error("no session was created");
  return value;
}

async function api(
  request: APIRequestContext,
  h: Handle,
  method: "get" | "post" | "delete",
  path: string,
  data?: unknown,
) {
  return request.fetch(`/e2e-ok/api/v1/sessions/${h.sessionId}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${h.token}`,
      "Idempotency-Key": `e2e-${Math.random().toString(36).slice(2)}`,
    },
    data,
  });
}

async function answerBaseline(page: Page, value: number): Promise<void> {
  await expect(page.getByRole("heading", { name: "Before we start" })).toBeVisible();
  await page.getByLabel(String(value), { exact: true }).check();
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByTestId("progress")).toContainText("1 of 3");
}

async function toFirstActivity(page: Page): Promise<void> {
  await startDemo(page);
  await answerBaseline(page, 3);
}

async function submitAnswer(page: Page, text: string): Promise<void> {
  await page.getByLabel("Your answer").fill(text);
  await page.getByRole("button", { name: "Check my answer" }).click();
  await expect(page.getByTestId("feedback")).toBeVisible();
}

test("full flow: demo preset, baseline, wrong answer, hint, adapted challenge, end check, summary, delete", async ({
  page,
  request,
}) => {
  await startDemo(page);

  // R-12.2: the generation stages are shown, sanitized, as complete.
  const timeline = page.getByTestId("timeline");
  await expect(timeline).toBeVisible();
  await expect(timeline).toHaveAttribute("data-source", "live");
  for (const stage of ["understand_objects", "choose_objective", "create_story"]) {
    await expect(page.getByTestId(`stage-${stage}`)).toHaveAttribute("data-state", "complete");
  }
  await expect(timeline).not.toContainText(/prompt|credential|reasoning/i);

  // R-07.1: the baseline comes before any Activity.
  await expect(page.getByTestId("progress")).toHaveCount(0);
  await answerBaseline(page, 3);

  // R-05.5: a hint gives a scaffold and never the expected answer.
  await page.getByRole("button", { name: "Show a hint" }).click();
  await expect(page.getByTestId("hint")).toBeVisible();
  await expect(page.getByTestId("expected-answer")).toHaveCount(0);

  // R-06.2: a wrong answer is not hidden; the next challenge is adapted and the change reported.
  await submitAnswer(page, "9");
  await expect(page.getByTestId("feedback")).toContainText("The lesson goal stays the same");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByTestId("progress")).toContainText("2 of 3");
  await page.getByRole("button", { name: "Show a hint" }).click();
  await expect(page.getByTestId("hint")).toContainText("Touch each item once as you count aloud.");

  await submitAnswer(page, "3");
  await expect(page.getByTestId("expected-answer")).toContainText("3");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByTestId("progress")).toContainText("3 of 3");
  await submitAnswer(page, "4");
  await page.getByRole("button", { name: "Next", exact: true }).click();

  // R-07.2 to R-07.5: end check, then the difference with the not-validated warning.
  await expect(page.getByRole("heading", { name: "One last check" })).toBeVisible();
  await page.getByLabel("4", { exact: true }).check();
  await page.getByRole("button", { name: "Submit answer" }).click();
  await expect(page.getByRole("heading", { name: "Session summary" })).toBeVisible();
  await expect(page.getByTestId("difference-value")).toContainText("1");
  await expect(page.getByTestId("not-validated-warning")).toContainText("not a validated");
  await expect(page.getByTestId("provisional")).toContainText("Provisional estimate");

  // R-10.5, R-10.6: delete confirms, then the session is gone.
  const h = await handle(page);
  await page.getByRole("button", { name: "Delete session" }).click();
  await page.getByRole("button", { name: "Yes, delete" }).click();
  await expect(page.getByText("This session was deleted.")).toBeVisible();
  const after = await api(request, h, "get", "");
  expect(after.status()).toBe(404);
});

test("skipping the baseline still reaches a summary without a difference (R-07.3, R-07.4)", async ({
  page,
}) => {
  await startDemo(page);
  await page.getByRole("button", { name: "Skip this question" }).click();
  await expect(page.getByTestId("progress")).toContainText("1 of 3");
  await page.getByRole("button", { name: "End session" }).click();
  await expect(page.getByRole("heading", { name: "Session summary" })).toBeVisible();
  await expect(page.getByTestId("difference")).toHaveCount(0);
});

test("model failure: retry and Safe_Template are offered and no lesson is shown (R-03.5, NFR-05)", async ({
  page,
}) => {
  await startDemo(page, "fail");
  const alert = page.getByTestId("generation-failed");
  await expect(alert).toBeVisible();
  await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(alert.getByRole("button", { name: "Use a safe template" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Before we start" })).toHaveCount(0);

  // The failure is repeatable and leaves the page usable.
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByTestId("generation-failed")).toBeVisible();
});

test("Stop: later writes are rejected and the session stays readable (R-08.3)", async ({
  page,
  request,
}) => {
  await toFirstActivity(page);
  const h = await handle(page);
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Session stopped" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop", exact: true })).toHaveCount(0);

  const write = await api(request, h, "post", "/answers", { answer: "2" });
  expect(write.status()).toBe(409);
  expect((await write.json()).code).toBe("session_stopped");
  const read = await api(request, h, "get", "/learner-view");
  expect(read.status()).toBe(200);
});

test("expired session: the save fails, typed work stays and a retry is offered (R-10.8, R-10.9)", async ({
  page,
  request,
}) => {
  await toFirstActivity(page);
  const h = await handle(page);
  await page.getByLabel("Your answer").fill("2");
  const expire = await request.post(`/e2e-ok/__e2e/expire/${h.sessionId}`);
  expect(expire.status()).toBe(204);

  await page.getByRole("button", { name: "Check my answer" }).click();
  await expect(page.getByTestId("save-error")).toBeVisible();
  await expect(page.getByTestId("save-error")).toContainText("Your work is still here");
  await expect(page.getByLabel("Your answer")).toHaveValue("2");
  await expect(page.getByRole("button", { name: "Try again" })).toBeEnabled();

  const read = await api(request, h, "get", "/learner-view");
  expect(read.status()).toBe(410);
});
