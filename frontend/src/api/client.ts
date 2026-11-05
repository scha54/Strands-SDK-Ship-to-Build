// Typed API client.
//
// A thin fetch wrapper around the backend's `/api/v1` surface. Request and
// response shapes come from the generated OpenAPI types (R-04.3; NFR-02), so
// the client stays in lock-step with the backend contract. Session routes are
// implemented in later tasks; this module establishes the typed transport,
// bearer-token handling and structured error type the UI relies on.
import type { ApiError } from "./types";

const DEFAULT_BASE_URL = "/api/v1";

/** Error thrown when the API returns a non-2xx response. */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly body: ApiError | null;

  constructor(status: number, message: string, body: ApiError | null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.body = body;
  }
}

export interface ApiClientOptions {
  /** Base URL for the API. Defaults to the same-origin `/api/v1`. */
  baseUrl?: string;
  /** Capability bearer token returned when a session is created. */
  token?: string;
  /** Injectable fetch implementation (eases testing). */
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  method?: string;
  /** JSON-serialisable request body. */
  body?: unknown;
  /** Idempotency key for mutating requests. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly token: string | undefined;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.token = options.token;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  /** Returns a copy of this client that sends the given bearer token. */
  withToken(token: string): ApiClient {
    return new ApiClient({
      baseUrl: this.baseUrl,
      token,
      fetchImpl: this.fetchImpl,
    });
  }

  /** Perform a typed JSON request and return the parsed response body. */
  async request<TResponse>(
    path: string,
    options: RequestOptions = {},
  ): Promise<TResponse> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (options.idempotencyKey) {
      headers["Idempotency-Key"] = options.idempotencyKey;
    }

    const init: RequestInit = { method: options.method ?? "GET", headers };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    if (options.signal) init.signal = options.signal;

    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    return parseResponse<TResponse>(response);
  }
}

async function parseResponse<TResponse>(
  response: Response,
): Promise<TResponse> {
  const text = await response.text();
  const data: unknown = text ? safeJsonParse(text) : null;

  if (!response.ok) {
    const body = isApiError(data) ? data : null;
    const message = body?.message ?? `Request failed with status ${response.status}`;
    throw new ApiRequestError(response.status, message, body);
  }

  return data as TResponse;
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isApiError(value: unknown): value is ApiError {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.code === "string" &&
    typeof v.message === "string" &&
    typeof v.correlation_id === "string"
  );
}
