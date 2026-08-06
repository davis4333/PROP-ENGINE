import type {
  AdminStatusResponse,
  GradeActionResponse,
  LedgerResponse,
  LineImportCommitResponse,
  LineImportEntryIn,
  LineImportPreviewResponse,
  ProjectionHistoryResponse,
  RunActionResponse,
  TodayResponse,
} from "./types";

/** Server Components (Today/Ledger) run inside the Next.js server process
 * and need an absolute, server-reachable URL to the engine -- API_BASE_URL
 * (no NEXT_PUBLIC_ prefix, never sent to the browser). The Admin page is a
 * Client Component; its browser-side fetches use relative `/api/...`
 * paths instead, proxied to the engine by next.config.ts's rewrite --
 * see that file for why (single public origin, works the same locally,
 * in docker-compose, and on a single-port host like Replit). Both
 * server-side and the rewrite default to the engine's docker-compose
 * port for local dev. */
export function serverApiBaseUrl(): string {
  return process.env.API_BASE_URL ?? "http://localhost:8000";
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

// Client-side (Admin page) -- relative paths, proxied by next.config.ts.
export function fetchAdminStatus(secret: string): Promise<AdminStatusResponse> {
  return getJson(`/api/admin/status`, { "X-Admin-Secret": secret });
}

export function triggerRun(
  slateDate: string,
  secret: string,
): Promise<RunActionResponse> {
  return postJson(
    `/api/admin/runs/${encodeURIComponent(slateDate)}/run`,
    { "X-Admin-Secret": secret },
    {},
  );
}

export function triggerGrade(
  slateDate: string,
  secret: string,
): Promise<GradeActionResponse> {
  return postJson(`/api/admin/runs/${encodeURIComponent(slateDate)}/grade`, {
    "X-Admin-Secret": secret,
  });
}

export function previewLineImport(
  slateDate: string,
  entries: LineImportEntryIn[],
  secret: string,
): Promise<LineImportPreviewResponse> {
  return postJson(
    `/api/admin/lines/${encodeURIComponent(slateDate)}/preview`,
    { "X-Admin-Secret": secret },
    { entries },
  );
}

export function importLines(
  slateDate: string,
  entries: LineImportEntryIn[],
  secret: string,
): Promise<LineImportCommitResponse> {
  return postJson(
    `/api/admin/lines/${encodeURIComponent(slateDate)}/import`,
    { "X-Admin-Secret": secret },
    { entries },
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
