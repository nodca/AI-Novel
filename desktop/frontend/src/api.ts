import type {
  ConsistencyBatchReprocessResult,
  ChapterSnapshot,
  ConsistencyIssue,
  ConsistencyIssueJumpInfo,
  ConsistencyIssueStatus,
  ConsistencySummary,
  CostSummary,
  JobInfo,
  ModelCenterConfig,
  ProjectImportResult,
  ProjectInfo,
  RestoreSnapshotResult,
  SnapshotDiff,
  UsageEvent
} from "./types";

declare global {
  interface Window {
    aiNovelDesktop?: {
      apiBaseUrl?: string;
      platform?: string;
      pickDirectory?: () => Promise<string | null>;
    };
  }
}

const API_BASE = window.aiNovelDesktop?.apiBaseUrl ?? "http://127.0.0.1:8008";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `HTTP ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export async function health(): Promise<{ status: string; active_project_id: string | null }> {
  return request("/api/v1/health");
}

export async function listProjects(): Promise<ProjectInfo[]> {
  const data = await request<{ items: ProjectInfo[] }>("/api/v1/projects");
  return data.items;
}

export async function createProject(name: string): Promise<ProjectInfo> {
  return request<ProjectInfo>("/api/v1/projects", {
    method: "POST",
    body: JSON.stringify({ name })
  });
}

export async function importProjectContent(
  projectId: string,
  payload: {
    sourceRoot: string;
    overwrite?: boolean;
    importDatabase?: boolean;
    importLightrag?: boolean;
  }
): Promise<ProjectImportResult> {
  return request<ProjectImportResult>(`/api/v1/projects/${projectId}/import`, {
    method: "POST",
    body: JSON.stringify({
      source_root: payload.sourceRoot,
      overwrite: payload.overwrite ?? true,
      import_database: payload.importDatabase ?? true,
      import_lightrag: payload.importLightrag ?? true
    })
  });
}

export async function pickDirectory(): Promise<string | null> {
  if (!window.aiNovelDesktop?.pickDirectory) {
    return null;
  }
  return window.aiNovelDesktop.pickDirectory();
}

export async function activateProject(projectId: string): Promise<ProjectInfo> {
  return request<ProjectInfo>(`/api/v1/projects/${projectId}/activate`, {
    method: "POST"
  });
}

export async function listJobs(projectId: string): Promise<JobInfo[]> {
  const data = await request<{ items: JobInfo[] }>(`/api/v1/projects/${projectId}/jobs`);
  return data.items;
}

export async function enqueueJob(
  projectId: string,
  jobType: JobInfo["job_type"],
  payload: Record<string, unknown>
): Promise<JobInfo> {
  return request<JobInfo>(`/api/v1/projects/${projectId}/jobs`, {
    method: "POST",
    body: JSON.stringify({ job_type: jobType, payload })
  });
}

export async function cancelJob(jobId: string): Promise<JobInfo> {
  return request<JobInfo>(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function pauseJob(jobId: string): Promise<JobInfo> {
  return request<JobInfo>(`/api/v1/jobs/${jobId}/pause`, { method: "POST" });
}

export async function resumeJob(jobId: string): Promise<JobInfo> {
  return request<JobInfo>(`/api/v1/jobs/${jobId}/resume`, { method: "POST" });
}

export async function getCostSummary(projectId: string, days = 30): Promise<CostSummary> {
  return request<CostSummary>(`/api/v1/projects/${projectId}/costs/summary?days=${days}`);
}

export async function listUsageEvents(
  projectId: string,
  days = 30,
  limit = 50
): Promise<UsageEvent[]> {
  return request<UsageEvent[]>(
    `/api/v1/projects/${projectId}/costs/events?days=${days}&limit=${limit}`
  );
}

export async function getModelCenter(projectId: string): Promise<ModelCenterConfig> {
  return request<ModelCenterConfig>(`/api/v1/projects/${projectId}/model-center`);
}

export async function updateModelCenter(
  projectId: string,
  payload: ModelCenterConfig
): Promise<ModelCenterConfig> {
  return request<ModelCenterConfig>(`/api/v1/projects/${projectId}/model-center`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getConsistencySummary(projectId: string, days = 90): Promise<ConsistencySummary> {
  return request<ConsistencySummary>(`/api/v1/projects/${projectId}/consistency/summary?days=${days}`);
}

export async function listConsistencyIssues(
  projectId: string,
  opts?: {
    days?: number;
    limit?: number;
    status?: string;
    severity?: string;
    chapterNumber?: number;
  }
): Promise<ConsistencyIssue[]> {
  const params = new URLSearchParams();
  params.set("days", String(opts?.days ?? 90));
  params.set("limit", String(opts?.limit ?? 200));
  if (opts?.status) params.set("status", opts.status);
  if (opts?.severity) params.set("severity", opts.severity);
  if (opts?.chapterNumber != null) params.set("chapter_number", String(opts.chapterNumber));
  const data = await request<{ items: ConsistencyIssue[] }>(
    `/api/v1/projects/${projectId}/consistency/issues?${params.toString()}`
  );
  return data.items;
}

export async function updateConsistencyIssueStatus(
  projectId: string,
  issueId: number,
  status: ConsistencyIssueStatus
): Promise<ConsistencyIssue> {
  return request<ConsistencyIssue>(`/api/v1/projects/${projectId}/consistency/issues/${issueId}`, {
    method: "PATCH",
    body: JSON.stringify({ status })
  });
}

export async function getConsistencyIssueJump(
  projectId: string,
  issueId: number
): Promise<ConsistencyIssueJumpInfo> {
  return request<ConsistencyIssueJumpInfo>(`/api/v1/projects/${projectId}/consistency/issues/${issueId}/jump`);
}

export async function enqueueConsistencyOpenErrorReprocess(
  projectId: string,
  opts?: { days?: number; maxChapters?: number; skipIfBusy?: boolean }
): Promise<ConsistencyBatchReprocessResult> {
  return request<ConsistencyBatchReprocessResult>(
    `/api/v1/projects/${projectId}/consistency/reprocess-open-errors`,
    {
      method: "POST",
      body: JSON.stringify({
        days: opts?.days ?? 90,
        max_chapters: opts?.maxChapters ?? 30,
        skip_if_busy: opts?.skipIfBusy ?? true
      })
    }
  );
}

export async function listSnapshots(
  projectId: string,
  opts?: {
    chapterNumber?: number;
    limit?: number;
    query?: string;
    tags?: string[];
    favoritesOnly?: boolean;
  }
): Promise<ChapterSnapshot[]> {
  const params = new URLSearchParams();
  params.set("limit", String(opts?.limit ?? 120));
  if (opts?.chapterNumber != null) params.set("chapter_number", String(opts.chapterNumber));
  if (opts?.query) params.set("q", opts.query);
  if (opts?.tags?.length) params.set("tags", opts.tags.join(","));
  if (opts?.favoritesOnly) params.set("favorites_only", "true");
  const data = await request<{ items: ChapterSnapshot[] }>(
    `/api/v1/projects/${projectId}/snapshots?${params.toString()}`
  );
  return data.items;
}

export async function createSnapshot(
  projectId: string,
  chapterNumber: number,
  note = "",
  tags: string[] = [],
  isFavorite = false
): Promise<ChapterSnapshot> {
  return request<ChapterSnapshot>(`/api/v1/projects/${projectId}/snapshots`, {
    method: "POST",
    body: JSON.stringify({ chapter_number: chapterNumber, note, tags, is_favorite: isFavorite })
  });
}

export async function updateSnapshot(
  projectId: string,
  snapshotId: number,
  patch: { note?: string; tags?: string[]; isFavorite?: boolean }
): Promise<ChapterSnapshot> {
  return request<ChapterSnapshot>(`/api/v1/projects/${projectId}/snapshots/${snapshotId}`, {
    method: "PATCH",
    body: JSON.stringify({
      note: patch.note,
      tags: patch.tags,
      is_favorite: patch.isFavorite
    })
  });
}

export async function restoreSnapshot(
  projectId: string,
  snapshotId: number,
  reprocess: boolean
): Promise<RestoreSnapshotResult> {
  return request<RestoreSnapshotResult>(`/api/v1/projects/${projectId}/snapshots/${snapshotId}/restore`, {
    method: "POST",
    body: JSON.stringify({ reprocess })
  });
}

export async function getSnapshotDiff(
  projectId: string,
  snapshotId: number,
  contextLines = 2
): Promise<SnapshotDiff> {
  return request<SnapshotDiff>(
    `/api/v1/projects/${projectId}/snapshots/${snapshotId}/diff?context_lines=${contextLines}`
  );
}
