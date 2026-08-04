import type {
  AdminStatusResponse,
  GradeActionResponse,
  LedgerResponse,
  ProjectionHistoryResponse,
  RunActionResponse,
  TodayResponse,
} from "./types";

/** Server Components (Today/Ledger) run inside the Next.js server process
 * and need an absolute, server-reachable URL -- API_BASE_URL (no
 * NEXT_PUBLIC_ prefix, never sent to the browser). The Admin page is a
 * Client Component and fetches from the browser, so it needs the public
 * variant instead. Both default to the engine's docker-compose port for
 * local dev. */
export function serverApiBaseUrl(): string {
  return process.env.API_BASE_URL ?? "http://localhost:8000";
}

export function publicApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(url: string, headers?: HeadersInit): Promise<T> {
  const response = await fetch(url, { headers, cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `${response.status} ${response.statusText} for ${url}`,
    );
  }
  return (await response.json()) as T;
}

async function postJson<T>(
  url: string,
  headers?: HeadersInit,
  body?: unknown,
): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `${response.status} ${response.statusText} for ${url}`,
    );
  }
  return (await response.json()) as T;
}

export function fetchToday(slateDate?: string): Promise<TodayResponse> {
  const params = slateDate
    ? `?slate_date=${encodeURIComponent(slateDate)}`
    : "";
  return getJson(`${serverApiBaseUrl()}/api/today${params}`);
}

export function fetchLedger(slateDate?: string): Promise<LedgerResponse> {
  const params = slateDate
    ? `?slate_date=${encodeURIComponent(slateDate)}`
    : "";
  return getJson(`${serverApiBaseUrl()}/api/ledger${params}`);
}

export function fetchProjectionHistory(
  projectionId: string,
): Promise<ProjectionHistoryResponse> {
  return getJson(
    `${serverApiBaseUrl()}/api/ledger/${encodeURIComponent(projectionId)}`,
  );
}

export function fetchAdminStatus(secret: string): Promise<AdminStatusResponse> {
  return getJson(`${publicApiBaseUrl()}/api/admin/status`, {
    "X-Admin-Secret": secret,
  });
}

export function triggerRun(
  slateDate: string,
  secret: string,
): Promise<RunActionResponse> {
  return postJson(
    `${publicApiBaseUrl()}/api/admin/runs/${encodeURIComponent(slateDate)}/run`,
    { "X-Admin-Secret": secret },
    {},
  );
}

export function triggerGrade(
  slateDate: string,
  secret: string,
): Promise<GradeActionResponse> {
  return postJson(
    `${publicApiBaseUrl()}/api/admin/runs/${encodeURIComponent(slateDate)}/grade`,
    {
      "X-Admin-Secret": secret,
    },
  );
}

export const PIPELINE_STAGES = [
  "INGEST",
  "VALIDATE",
  "FREEZE",
  "PROJECT",
  "REVIEW",
  "PUBLISH",
  "GRADE",
] as const;
