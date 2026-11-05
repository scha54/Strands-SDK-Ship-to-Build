// Unit and property tests for the typed API client transport.
//
// Validates: Requirements R-01.2 / R-06.1 (typed contract transport), NFR-02
// (typed inputs/outputs and output sanitisation), NFR-05 (structured error
// handling). These exercise the transport layer only; session routes arrive in
// later tasks.
import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiRequestError } from "./client";
import type { ApiError } from "./types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiClient", () => {
  it("sends the bearer token and parses a typed JSON response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(200, { ok: true }),
    );
    const client = new ApiClient({
      baseUrl: "/api/v1",
      token: "secret-token",
      fetchImpl,
    });

    const result = await client.request<{ ok: boolean }>("/sessions/abc");

    expect(result).toEqual({ ok: true });
    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer secret-token");
  });

  it("serialises the body and forwards an idempotency key on mutations", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(202, {}));
    const client = new ApiClient({ fetchImpl });

    await client.request("/sessions/abc/answers", {
      method: "POST",
      body: { answer: "7" },
      idempotencyKey: "key-1",
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/sessions/abc/answers");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ answer: "7" }));
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe("key-1");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("throws a structured ApiRequestError on error responses (NFR-05)", async () => {
    const errorBody: ApiError = {
      code: "not_found",
      message: "Session not found",
      correlation_id: "corr-123",
      details: null,
    };
    // A fresh Response per call: a Response body can only be read once.
    const fetchImpl = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(404, errorBody)));
    const client = new ApiClient({ fetchImpl });

    const error = await client.request("/sessions/missing").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect(error).toMatchObject({ status: 404, message: "Session not found" });
    expect((error as ApiRequestError).body).toMatchObject({
      code: "not_found",
      correlation_id: "corr-123",
    });
  });

  it("property: never attaches an Authorization header without a token (NFR-02)", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 1, maxLength: 40 }),
        async (segment) => {
          const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, {}));
          const client = new ApiClient({ fetchImpl });

          await client.request(`/${encodeURIComponent(segment)}`);

          const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
          const headers = init.headers as Record<string, string>;
          return !("Authorization" in headers);
        },
      ),
      { numRuns: 100 },
    );
  });
});
