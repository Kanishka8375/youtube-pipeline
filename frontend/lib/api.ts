import { clearToken, getToken } from "@/lib/auth";
import type {
  AuditEntry,
  Job,
  Member,
  PipelineStage,
  PromptTemplate,
  ProviderInfo,
  User,
  Workspace
} from "@/lib/types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Set by the app shell so a 401 can bounce to the login screen. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {})
      },
      cache: "no-store"
    });
  } catch (cause) {
    // A failed fetch is almost always the backend being down or a CORS
    // rejection. Saying so beats surfacing "Failed to fetch".
    throw new ApiError(
      `Cannot reach the API at ${API_BASE}. Is the backend running?`,
      0
    );
  }

  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }

  if (!response.ok) {
    if (response.status === 401) {
      clearToken();
      onUnauthorized?.();
    }
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : null;
    throw new ApiError(
      typeof detail === "string" ? detail : `Request failed (${response.status})`,
      response.status
    );
  }

  return body as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in_minutes: number }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) }
    ),
  register: (email: string, full_name: string, password: string) =>
    request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, full_name, password })
    }),
  me: () => request<User>("/auth/me"),

  workspaces: () => request<Workspace[]>("/workspaces"),
  createWorkspace: (name: string) =>
    request<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name }) }),
  members: (slug: string) => request<Member[]>(`/workspaces/${slug}/members`),
  auditLog: (slug: string) => request<AuditEntry[]>(`/workspaces/${slug}/audit-log`),

  jobs: () => request<Job[]>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  jobHandlers: () => request<{ job_types: string[] }>("/jobs/handlers"),
  drain: (max_jobs = 25) =>
    request<{ ran: number; outcomes: Array<{ job_id: string; job_type: string; status: string; error: string | null }> }>(
      "/jobs/drain",
      { method: "POST", body: JSON.stringify({ max_jobs }) }
    ),

  templates: () => request<{ templates: PromptTemplate[] }>("/generation/templates"),
  providers: () => request<{ providers: Record<string, ProviderInfo> }>("/generation/providers"),
  previewPrompt: (template_key: string, episode_code: string) =>
    request<{ template_key: string; system: string; prompt: string; prompt_chars: number }>(
      "/generation/preview",
      { method: "POST", body: JSON.stringify({ template_key, episode_code }) }
    ),
  runGeneration: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/generation/run", {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  pipelineStages: () => request<PipelineStage[]>("/pipeline/stages"),
  evaluationSuite: () =>
    request<{ suite_code: string; case_count: number; cases: Array<{ case_code: string; category: string; description: string; expects_block: boolean }> }>(
      "/evaluation/suite"
    ),
  runEvaluation: () =>
    request<{
      run_code: string;
      passed: number;
      total: number;
      pass_rate: number;
      by_polarity: Record<string, { total: number; passed: number; failed: number }>;
      by_category: Record<string, { total: number; passed: number; failed: number }>;
      failures: Array<{ case_code: string; category: string; description: string; failure_reason: string }>;
    }>("/evaluation/runs", { method: "POST", body: JSON.stringify({ target: "admin_ui" }) }),

  readiness: () => request<Record<string, string>>("/system/readiness")
};
