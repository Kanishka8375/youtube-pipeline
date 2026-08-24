export type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
};

export type Workspace = {
  id: string;
  name: string;
  slug: string;
  settings_json: Record<string, unknown>;
};

export type Member = {
  user_id: string;
  email: string | null;
  full_name: string | null;
  role: "owner" | "editor" | "member" | "viewer";
};

export type JobStatus = "queued" | "running" | "retrying" | "completed" | "failed";

export type Job = {
  id: string;
  job_type: string;
  status: JobStatus;
  attempt_count: number;
  max_attempts: number;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  error_message: string | null;
  correlation_id: string | null;
  scheduled_for: string | null;
  created_at: string;
};

export type PromptTemplate = {
  key: string;
  purpose: string;
  variables: string[];
  has_system_prompt: boolean;
};

export type ProviderInfo = {
  provider_key: string;
  default_model: string | null;
  configured: boolean;
};

/** A media provider also declares which kinds it can produce. */
export type MediaProviderInfo = ProviderInfo & {
  kinds: string[];
};

export type AuditEntry = {
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_user_id: string | null;
  message: string | null;
  correlation_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type PipelineStage = {
  name: string;
  agent: string;
  task_type: string;
  category: string;
  output_schema: string;
  depends_on: string[];
  approval_required: boolean;
  qc_gate: string | null;
  parallel_group: string | null;
};
