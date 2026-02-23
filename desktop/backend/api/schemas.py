"""Pydantic schemas for desktop API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

JobType = Literal["init_project", "write_chapter", "batch_write", "reprocess"]
JobStatus = Literal["queued", "running", "completed", "failed", "canceled"]
ConsistencyIssueStatus = Literal["open", "resolved", "ignored"]
ConsistencyIssueSeverity = Literal["error", "warning"]
SnapshotSourceType = Literal["manual", "auto_write", "restore_backup"]


class ProjectCreateRequest(BaseModel):
    """Request payload for creating a project workspace."""

    name: str = Field(min_length=1, max_length=120)


class ProjectConfigPatchRequest(BaseModel):
    """Partial config patch payload."""

    patch: Dict[str, Any] = Field(default_factory=dict)


class ProjectImportRequest(BaseModel):
    """Import existing local novel files into current project workspace."""

    source_root: str = Field(min_length=1)
    overwrite: bool = True
    import_database: bool = True
    import_lightrag: bool = True


class ProjectImportResponse(BaseModel):
    """Import result summary."""

    project_id: str
    workspace_dir: str
    imported: Dict[str, str] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    chapter_files: int = 0


class ProjectInfo(BaseModel):
    """Project summary for project lists/detail pages."""

    id: str
    name: str
    slug: str
    workspace_dir: str
    config_path: str
    is_active: bool
    created_at: str
    updated_at: str


class JobCreateRequest(BaseModel):
    """Request payload for queueing a generation job."""

    job_type: JobType
    payload: Dict[str, Any] = Field(default_factory=dict)


class JobInfo(BaseModel):
    """Job summary for queues and detail panes."""

    id: str
    project_id: str
    job_type: str
    status: JobStatus
    payload: Dict[str, Any]
    current_stage: Optional[str] = None
    current_chapter: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    """Projects API response."""

    items: List[ProjectInfo]


class JobListResponse(BaseModel):
    """Jobs API response."""

    items: List[JobInfo]


class UsageEventInfo(BaseModel):
    """Single model usage event record."""

    id: int
    project_id: str
    job_id: Optional[str] = None
    chapter_number: Optional[int] = None
    stage: Optional[str] = None
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    latency_ms: int = 0
    cost_estimate_usd: float = 0.0
    created_at: str


class CostByModel(BaseModel):
    """Per-model cost breakdown row."""

    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_estimate_usd: float


class CostSummaryResponse(BaseModel):
    """Aggregated cost metrics for project dashboards."""

    project_id: str
    period_days: int
    calls: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_estimate_usd: float
    by_model: List[CostByModel]


class ModelProviderConfig(BaseModel):
    """Provider endpoint config (key + base_url)."""

    kind: str = "custom"
    api_key: str = ""
    base_url: str = ""


class ModelRoleConfig(BaseModel):
    """Role binding config (model and role-scoped params)."""

    provider: str
    model: str = ""
    temperature: Optional[float] = None
    timeout: Optional[int] = None
    max_tokens: Optional[int] = None
    dim: Optional[int] = None


class ModelCenterConfig(BaseModel):
    """Unified model configuration center payload."""

    providers: Dict[str, ModelProviderConfig] = Field(default_factory=dict)
    roles: Dict[str, ModelRoleConfig] = Field(default_factory=dict)
    runtime: Dict[str, Any] = Field(default_factory=dict)
    pricing_usd_per_million: Dict[str, Dict[str, float]] = Field(default_factory=dict)


class ConsistencyIssueInfo(BaseModel):
    """Single consistency issue row."""

    id: int
    project_id: str
    job_id: Optional[str] = None
    chapter_number: Optional[int] = None
    issue_type: str
    severity: ConsistencyIssueSeverity
    description: str
    location: str = ""
    fix_instruction: str = ""
    status: ConsistencyIssueStatus = "open"
    phase: str = "final"
    created_at: str
    updated_at: str


class ConsistencyIssueListResponse(BaseModel):
    """Consistency issue list API response."""

    items: List[ConsistencyIssueInfo]


class ConsistencyIssueTypeCount(BaseModel):
    """Consistency issue count grouped by issue_type."""

    issue_type: str
    count: int


class ConsistencySummaryResponse(BaseModel):
    """Aggregated consistency metrics for dashboards."""

    project_id: str
    period_days: int
    total: int
    open_count: int
    resolved_count: int
    ignored_count: int
    error_count: int
    warning_count: int
    by_type: List[ConsistencyIssueTypeCount]


class ConsistencyIssueStatusUpdateRequest(BaseModel):
    """Payload for mutating consistency issue workflow status."""

    status: ConsistencyIssueStatus


class ConsistencyIssueJumpInfo(BaseModel):
    """Issue + chapter file jump hint for quick navigation."""

    issue: ConsistencyIssueInfo
    chapter_file_path: str
    scene_number: Optional[int] = None
    line_hint: Optional[int] = None


class ConsistencyBatchReprocessRequest(BaseModel):
    """Batch reprocess request for open/error consistency issues."""

    days: int = Field(default=90, ge=1, le=365)
    max_chapters: int = Field(default=30, ge=1, le=300)
    skip_if_busy: bool = True


class ConsistencyBatchReprocessResponse(BaseModel):
    """Batch reprocess result for consistency center."""

    project_id: str
    period_days: int
    matched_issue_count: int
    matched_chapters: List[int]
    queued_jobs: List[JobInfo]
    skipped_chapters: List[int]
    truncated: bool = False


class ChapterSnapshotInfo(BaseModel):
    """Single chapter snapshot metadata."""

    id: int
    project_id: str
    chapter_number: int
    chapter_title: str = ""
    source_type: SnapshotSourceType
    note: str = ""
    tags: List[str] = Field(default_factory=list)
    is_favorite: bool = False
    chapter_file_path: str
    snapshot_path: str
    created_at: str


class ChapterSnapshotListResponse(BaseModel):
    """Chapter snapshot list response."""

    items: List[ChapterSnapshotInfo]


class ChapterSnapshotCreateRequest(BaseModel):
    """Create snapshot request payload."""

    chapter_number: int = Field(ge=1)
    note: str = ""
    tags: List[str] = Field(default_factory=list)
    is_favorite: bool = False


class ChapterSnapshotPatchRequest(BaseModel):
    """Patch snapshot metadata request payload."""

    note: Optional[str] = None
    tags: Optional[List[str]] = None
    is_favorite: Optional[bool] = None


class ChapterSnapshotRestoreRequest(BaseModel):
    """Restore snapshot request payload."""

    reprocess: bool = False


class ChapterSnapshotRestoreResponse(BaseModel):
    """Restore snapshot API response."""

    snapshot: ChapterSnapshotInfo
    restored_chapter_file: str
    backup_snapshot: Optional[ChapterSnapshotInfo] = None
    queued_reprocess_job: Optional[JobInfo] = None


class ChapterSnapshotDiffResponse(BaseModel):
    """Unified diff payload for snapshot vs current chapter file."""

    snapshot: ChapterSnapshotInfo
    current_chapter_file: str
    has_changes: bool
    diff_lines: List[str]
