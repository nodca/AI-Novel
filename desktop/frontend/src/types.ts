export type ProjectInfo = {
  id: string;
  name: string;
  slug: string;
  workspace_dir: string;
  config_path: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ProjectImportResult = {
  project_id: string;
  workspace_dir: string;
  imported: Record<string, string>;
  warnings: string[];
  chapter_files: number;
};

export type JobInfo = {
  id: string;
  project_id: string;
  job_type: "init_project" | "write_chapter" | "batch_write" | "reprocess";
  status: "queued" | "running" | "completed" | "failed" | "canceled";
  payload: Record<string, unknown>;
  current_stage?: string | null;
  current_chapter?: number | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type CostByModel = {
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_estimate_usd: number;
};

export type CostSummary = {
  project_id: string;
  period_days: number;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  cost_estimate_usd: number;
  by_model: CostByModel[];
};

export type UsageEvent = {
  id: number;
  project_id: string;
  job_id?: string | null;
  chapter_number?: number | null;
  stage?: string | null;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  latency_ms: number;
  cost_estimate_usd: number;
  created_at: string;
};

export type ModelProviderConfig = {
  kind: string;
  api_key: string;
  base_url: string;
};

export type ModelRoleConfig = {
  provider: string;
  model: string;
  temperature?: number | null;
  timeout?: number | null;
  max_tokens?: number | null;
  dim?: number | null;
};

export type ModelCenterConfig = {
  providers: Record<string, ModelProviderConfig>;
  roles: Record<string, ModelRoleConfig>;
  runtime: Record<string, unknown>;
  pricing_usd_per_million: Record<string, Record<string, number>>;
};

export type ConsistencyIssueStatus = "open" | "resolved" | "ignored";

export type ConsistencyIssueSeverity = "error" | "warning";

export type ConsistencyIssue = {
  id: number;
  project_id: string;
  job_id?: string | null;
  chapter_number?: number | null;
  issue_type: string;
  severity: ConsistencyIssueSeverity;
  description: string;
  location: string;
  fix_instruction: string;
  status: ConsistencyIssueStatus;
  phase: string;
  created_at: string;
  updated_at: string;
};

export type ConsistencyTypeCount = {
  issue_type: string;
  count: number;
};

export type ConsistencySummary = {
  project_id: string;
  period_days: number;
  total: number;
  open_count: number;
  resolved_count: number;
  ignored_count: number;
  error_count: number;
  warning_count: number;
  by_type: ConsistencyTypeCount[];
};

export type ConsistencyIssueJumpInfo = {
  issue: ConsistencyIssue;
  chapter_file_path: string;
  scene_number?: number | null;
  line_hint?: number | null;
};

export type ConsistencyBatchReprocessResult = {
  project_id: string;
  period_days: number;
  matched_issue_count: number;
  matched_chapters: number[];
  queued_jobs: JobInfo[];
  skipped_chapters: number[];
  truncated: boolean;
};

export type SnapshotSourceType = "manual" | "auto_write" | "restore_backup";

export type ChapterSnapshot = {
  id: number;
  project_id: string;
  chapter_number: number;
  chapter_title: string;
  source_type: SnapshotSourceType;
  note: string;
  tags: string[];
  is_favorite: boolean;
  chapter_file_path: string;
  snapshot_path: string;
  created_at: string;
};

export type RestoreSnapshotResult = {
  snapshot: ChapterSnapshot;
  restored_chapter_file: string;
  backup_snapshot?: ChapterSnapshot | null;
  queued_reprocess_job?: JobInfo | null;
};

export type SnapshotDiff = {
  snapshot: ChapterSnapshot;
  current_chapter_file: string;
  has_changes: boolean;
  diff_lines: string[];
};
