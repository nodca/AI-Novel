import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  activateProject,
  cancelJob,
  createSnapshot,
  createProject,
  enqueueJob,
  enqueueConsistencyOpenErrorReprocess,
  getConsistencyIssueJump,
  getConsistencySummary,
  getCostSummary,
  getModelCenter,
  getSnapshotDiff,
  health,
  importProjectContent,
  listConsistencyIssues,
  listJobs,
  listProjects,
  listSnapshots,
  listUsageEvents,
  pauseJob,
  pickDirectory,
  restoreSnapshot,
  resumeJob,
  updateSnapshot,
  updateConsistencyIssueStatus,
  updateModelCenter
} from "./api";
import type {
  ChapterSnapshot,
  ConsistencyIssue,
  ConsistencyIssueStatus,
  ConsistencySummary,
  CostSummary,
  JobInfo,
  ModelCenterConfig,
  ProjectInfo,
  SnapshotDiff,
  UsageEvent
} from "./types";

const PROVIDER_KIND_OPTIONS = ["anthropic", "openai_compatible", "custom"] as const;

const ROLE_LABELS: Record<string, string> = {
  writing: "写作",
  analysis: "分析",
  rag_llm: "RAG 检索 LLM",
  embedding: "向量嵌入",
  rerank: "重排"
};

const ROLE_HINTS: Record<string, string> = {
  writing: "正文生成主角色",
  analysis: "结构审查与总结",
  rag_llm: "知识检索问答",
  embedding: "文本向量化",
  rerank: "召回结果重排"
};

const ISSUE_TYPE_LABELS: Record<string, string> = {
  contract: "合同约束",
  fact_anchor: "事实锚点",
  timeline: "时间线",
  location: "地点连续性",
  foreshadow: "伏笔状态",
  knowledge: "认知冲突"
};

const ISSUE_STATUS_OPTIONS: Array<{ value: ConsistencyIssueStatus | "all"; label: string }> = [
  { value: "open", label: "待处理" },
  { value: "all", label: "全部" },
  { value: "resolved", label: "已解决" },
  { value: "ignored", label: "已忽略" }
];

type RoleNumericField = "temperature" | "timeout" | "max_tokens" | "dim";

function roleLabel(roleId: string): string {
  return ROLE_LABELS[roleId] ?? roleId;
}

function issueTypeLabel(issueType: string): string {
  return ISSUE_TYPE_LABELS[issueType] ?? issueType;
}

function parseTagInput(text: string): string[] {
  const parts = text
    .replace(/，/g, ",")
    .split(",")
    .map((item: string) => item.trim())
    .filter(Boolean);
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of parts) {
    const tag = raw.length > 28 ? raw.slice(0, 28) : raw;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
    if (out.length >= 12) break;
  }
  return out;
}

function shouldShowRoleField(
  roleId: string,
  role: ModelCenterConfig["roles"][string],
  field: RoleNumericField
): boolean {
  if (field === "temperature") {
    return roleId === "writing" || roleId === "analysis" || role.temperature != null;
  }
  if (field === "timeout") {
    return roleId === "rag_llm" || role.timeout != null;
  }
  if (field === "max_tokens") {
    return roleId === "rag_llm" || roleId === "embedding" || role.max_tokens != null;
  }
  if (field === "dim") {
    return roleId === "embedding" || role.dim != null;
  }
  return false;
}

export default function App() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string>("");
  const [newProjectName, setNewProjectName] = useState("");
  const [importSourceRoot, setImportSourceRoot] = useState("");
  const [importDatabase, setImportDatabase] = useState(true);
  const [importLightrag, setImportLightrag] = useState(true);
  const [importingProject, setImportingProject] = useState(false);
  const [importHint, setImportHint] = useState("");
  const [outlinePath, setOutlinePath] = useState("");
  const [chapterNumber, setChapterNumber] = useState("1");
  const [error, setError] = useState("");
  const [statusHint, setStatusHint] = useState("正在连接本地服务...");
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null);
  const [usageEvents, setUsageEvents] = useState<UsageEvent[]>([]);
  const [modelCenter, setModelCenter] = useState<ModelCenterConfig | null>(null);
  const [consistencySummary, setConsistencySummary] = useState<ConsistencySummary | null>(null);
  const [consistencyIssues, setConsistencyIssues] = useState<ConsistencyIssue[]>([]);
  const [consistencyStatusFilter, setConsistencyStatusFilter] =
    useState<ConsistencyIssueStatus | "all">("open");
  const [consistencySeverityFilter, setConsistencySeverityFilter] =
    useState<"all" | "error" | "warning">("all");
  const [consistencyChapterFilter, setConsistencyChapterFilter] = useState("");
  const [updatingIssueId, setUpdatingIssueId] = useState<number | null>(null);
  const [issueJumpHints, setIssueJumpHints] = useState<Record<number, string>>({});
  const [batchReprocessBusy, setBatchReprocessBusy] = useState(false);
  const [batchReprocessHint, setBatchReprocessHint] = useState("");
  const [snapshots, setSnapshots] = useState<ChapterSnapshot[]>([]);
  const [snapshotChapterNumber, setSnapshotChapterNumber] = useState("1");
  const [snapshotNote, setSnapshotNote] = useState("");
  const [snapshotCreateTags, setSnapshotCreateTags] = useState("");
  const [snapshotSearchQuery, setSnapshotSearchQuery] = useState("");
  const [snapshotFilterTags, setSnapshotFilterTags] = useState("");
  const [snapshotFavoritesOnly, setSnapshotFavoritesOnly] = useState(false);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [restoringSnapshotId, setRestoringSnapshotId] = useState<number | null>(null);
  const [loadingDiffSnapshotId, setLoadingDiffSnapshotId] = useState<number | null>(null);
  const [updatingSnapshotId, setUpdatingSnapshotId] = useState<number | null>(null);
  const [snapshotDiff, setSnapshotDiff] = useState<SnapshotDiff | null>(null);
  const [reprocessChapterNumber, setReprocessChapterNumber] = useState("1");
  const [reprocessBusy, setReprocessBusy] = useState(false);
  const [jobActionLoadingId, setJobActionLoadingId] = useState<string | null>(null);
  const [savingModelCenter, setSavingModelCenter] = useState(false);
  const [newProviderId, setNewProviderId] = useState("");
  const [newProviderKind, setNewProviderKind] =
    useState<(typeof PROVIDER_KIND_OPTIONS)[number]>("custom");
  const [visibleProviderKeys, setVisibleProviderKeys] = useState<Record<string, boolean>>({});

  const activeProject = useMemo(
    () => projects.find((p) => p.id === activeProjectId) ?? null,
    [projects, activeProjectId]
  );

  const providerIds = useMemo(
    () => (modelCenter ? Object.keys(modelCenter.providers).sort((a, b) => a.localeCompare(b)) : []),
    [modelCenter]
  );

  const roleEntries = useMemo(
    () =>
      modelCenter
        ? Object.entries(modelCenter.roles).sort(([a], [b]) => a.localeCompare(b))
        : [],
    [modelCenter]
  );

  const snapshotChapterSummary = useMemo(() => {
    const map = new Map<number, { count: number; favorites: number }>();
    for (const item of snapshots) {
      const chapter = Number(item.chapter_number);
      if (!Number.isFinite(chapter) || chapter <= 0) continue;
      const current = map.get(chapter) ?? { count: 0, favorites: 0 };
      current.count += 1;
      if (item.is_favorite) current.favorites += 1;
      map.set(chapter, current);
    }
    return Array.from(map.entries())
      .map(([chapter, stats]) => ({
        chapter,
        count: stats.count,
        favorites: stats.favorites
      }))
      .sort((a, b) => a.chapter - b.chapter);
  }, [snapshots]);

  async function refreshProjects() {
    const items = await listProjects();
    setProjects(items);
    const active = items.find((p) => p.is_active) ?? items[0];
    if (active) {
      setActiveProjectId(active.id);
    }
  }

  async function refreshJobs(projectId: string) {
    if (!projectId) return;
    const items = await listJobs(projectId);
    setJobs(items);
  }

  async function refreshCosts(projectId: string) {
    if (!projectId) return;
    const [summary, events] = await Promise.all([
      getCostSummary(projectId, 30),
      listUsageEvents(projectId, 30, 12)
    ]);
    setCostSummary(summary);
    setUsageEvents(events);
  }

  async function refreshModelCenter(projectId: string) {
    if (!projectId) return;
    const center = await getModelCenter(projectId);
    setModelCenter(center);
  }

  async function refreshConsistency(projectId: string) {
    if (!projectId) return;
    const chapterNumber = Number(consistencyChapterFilter);
    const [summary, issues] = await Promise.all([
      getConsistencySummary(projectId, 90),
      listConsistencyIssues(projectId, {
        days: 90,
        limit: 200,
        status: consistencyStatusFilter === "all" ? undefined : consistencyStatusFilter,
        severity: consistencySeverityFilter === "all" ? undefined : consistencySeverityFilter,
        chapterNumber: Number.isFinite(chapterNumber) && chapterNumber > 0 ? chapterNumber : undefined
      })
    ]);
    setConsistencySummary(summary);
    setConsistencyIssues(issues);
  }

  async function refreshSnapshots(projectId: string) {
    if (!projectId) return;
    const chapter = Number(snapshotChapterNumber);
    const tags = parseTagInput(snapshotFilterTags);
    const items = await listSnapshots(projectId, {
      chapterNumber: Number.isFinite(chapter) && chapter > 0 ? chapter : undefined,
      query: snapshotSearchQuery.trim() || undefined,
      tags: tags.length ? tags : undefined,
      favoritesOnly: snapshotFavoritesOnly,
      limit: 80
    });
    setSnapshots(items);
  }

  useEffect(() => {
    (async () => {
      try {
        const h = await health();
        setStatusHint(h.status === "ok" ? "本地服务已就绪" : "服务状态未知");
        await refreshProjects();
      } catch (err) {
        setStatusHint("未连接到本地服务");
        setError(err instanceof Error ? err.message : "服务连接失败");
      }
    })();
  }, []);

  useEffect(() => {
    if (!activeProjectId) return;
    setSnapshotDiff(null);
    setBatchReprocessHint("");
    setImportHint("");
    refreshJobs(activeProjectId).catch((err) => {
      setError(err instanceof Error ? err.message : "读取任务失败");
    });
    refreshCosts(activeProjectId).catch(() => undefined);
    refreshModelCenter(activeProjectId).catch(() => undefined);
    refreshConsistency(activeProjectId).catch(() => undefined);
    refreshSnapshots(activeProjectId).catch(() => undefined);
    const timer = window.setInterval(() => {
      refreshJobs(activeProjectId).catch(() => undefined);
      refreshCosts(activeProjectId).catch(() => undefined);
      refreshConsistency(activeProjectId).catch(() => undefined);
      refreshSnapshots(activeProjectId).catch(() => undefined);
    }, 3500);
    return () => clearInterval(timer);
  }, [
    activeProjectId,
    consistencyStatusFilter,
    consistencySeverityFilter,
    consistencyChapterFilter,
    snapshotChapterNumber,
    snapshotSearchQuery,
    snapshotFilterTags,
    snapshotFavoritesOnly
  ]);

  async function onCreateProject(e: FormEvent) {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    setError("");
    try {
      const created = await createProject(newProjectName.trim());
      setNewProjectName("");
      await refreshProjects();
      setActiveProjectId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建项目失败");
    }
  }

  async function chooseImportSourceDir() {
    setError("");
    try {
      const picked = await pickDirectory();
      if (picked) {
        setImportSourceRoot(picked);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "选择目录失败");
    }
  }

  async function importIntoActiveProject() {
    if (!activeProject) {
      setError("请先选择目标项目");
      return;
    }
    const sourceRoot = importSourceRoot.trim();
    if (!sourceRoot) {
      setError("请先选择要导入的小说目录");
      return;
    }
    setImportingProject(true);
    setError("");
    setImportHint("");
    try {
      const result = await importProjectContent(activeProject.id, {
        sourceRoot,
        overwrite: true,
        importDatabase,
        importLightrag
      });
      const importedNames = Object.keys(result.imported);
      const importedHint = importedNames.length
        ? `已同步：${importedNames.join("、")}`
        : "已完成目录导入";
      const warningHint = result.warnings.length
        ? `；提示：${result.warnings.join("；")}`
        : "";
      setImportHint(`导入完成：检测到 ${result.chapter_files} 个章节文件，${importedHint}${warningHint}`);
      await refreshProjects();
      await refreshJobs(activeProject.id);
      await refreshCosts(activeProject.id);
      await refreshModelCenter(activeProject.id);
      await refreshConsistency(activeProject.id);
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setImportingProject(false);
    }
  }

  async function onActivate(projectId: string) {
    setError("");
    try {
      const project = await activateProject(projectId);
      setActiveProjectId(project.id);
      await refreshProjects();
      await refreshJobs(project.id);
      await refreshCosts(project.id);
      await refreshModelCenter(project.id);
      await refreshConsistency(project.id);
      await refreshSnapshots(project.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换项目失败");
    }
  }

  async function queueInitProject() {
    if (!activeProject) return;
    setError("");
    try {
      await enqueueJob(activeProject.id, "init_project", {});
      await refreshJobs(activeProject.id);
      await refreshCosts(activeProject.id);
      await refreshModelCenter(activeProject.id);
      await refreshConsistency(activeProject.id);
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交任务失败");
    }
  }

  async function queueWriteChapter() {
    if (!activeProject) return;
    if (!outlinePath.trim()) {
      setError("请先填写细纲文件路径");
      return;
    }
    setError("");
    try {
      await enqueueJob(activeProject.id, "write_chapter", {
        outline_path: outlinePath.trim(),
        chapter_number: Number(chapterNumber)
      });
      await refreshJobs(activeProject.id);
      await refreshCosts(activeProject.id);
      await refreshModelCenter(activeProject.id);
      await refreshConsistency(activeProject.id);
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交写作任务失败");
    }
  }

  async function queueReprocessChapter(chapterText: string) {
    if (!activeProject) return;
    const chapter = Number(chapterText);
    if (!Number.isFinite(chapter) || chapter <= 0) {
      setError("请输入有效章节号");
      return;
    }
    setReprocessBusy(true);
    setError("");
    try {
      await enqueueJob(activeProject.id, "reprocess", { chapter_number: chapter });
      await refreshJobs(activeProject.id);
      await refreshConsistency(activeProject.id);
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交重处理任务失败");
    } finally {
      setReprocessBusy(false);
    }
  }

  function updateProviderField(
    providerId: string,
    field: "kind" | "api_key" | "base_url",
    value: string
  ) {
    setModelCenter((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        providers: {
          ...prev.providers,
          [providerId]: {
            ...(prev.providers[providerId] ?? { kind: "custom", api_key: "", base_url: "" }),
            [field]: value
          }
        }
      };
    });
  }

  function toggleProviderKeyVisible(providerId: string) {
    setVisibleProviderKeys((prev) => ({
      ...prev,
      [providerId]: !prev[providerId]
    }));
  }

  function addProvider() {
    if (!modelCenter) return;
    const providerId = newProviderId.trim();
    if (!providerId) {
      setError("请先填写 provider_id");
      return;
    }
    if (!/^[a-zA-Z0-9._-]+$/.test(providerId)) {
      setError("provider_id 仅支持字母、数字、点、下划线和短横线");
      return;
    }
    if (modelCenter.providers[providerId]) {
      setError(`Provider ${providerId} 已存在`);
      return;
    }
    setError("");
    setModelCenter((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        providers: {
          ...prev.providers,
          [providerId]: {
            kind: newProviderKind,
            api_key: "",
            base_url: ""
          }
        }
      };
    });
    setNewProviderId("");
  }

  function removeProvider(providerId: string) {
    if (!modelCenter) return;
    const boundRoles = Object.entries(modelCenter.roles)
      .filter(([, role]) => role.provider === providerId)
      .map(([roleId]) => roleLabel(roleId));
    if (boundRoles.length) {
      setError(`Provider ${providerId} 正在被以下角色使用：${boundRoles.join(" / ")}`);
      return;
    }
    setError("");
    setModelCenter((prev) => {
      if (!prev) return prev;
      const nextProviders = { ...prev.providers };
      delete nextProviders[providerId];
      return {
        ...prev,
        providers: nextProviders
      };
    });
    setVisibleProviderKeys((prev) => {
      const next = { ...prev };
      delete next[providerId];
      return next;
    });
  }

  function updateRoleProvider(roleId: string, providerId: string) {
    setModelCenter((prev) => {
      if (!prev) return prev;
      const current = prev.roles[roleId] ?? { provider: "", model: "" };
      return {
        ...prev,
        roles: {
          ...prev.roles,
          [roleId]: {
            ...current,
            provider: providerId
          }
        }
      };
    });
  }

  function updateRoleField(
    roleId: string,
    field: "model" | "temperature" | "timeout" | "max_tokens" | "dim",
    value: string
  ) {
    setModelCenter((prev) => {
      if (!prev) return prev;
      const current = prev.roles[roleId] ?? { provider: "", model: "" };
      const next: Record<string, unknown> = { ...current };
      if (field === "model") {
        next[field] = value;
      } else if (value.trim() === "") {
        next[field] = null;
      } else {
        const parsed = Number(value);
        next[field] = Number.isFinite(parsed) ? parsed : null;
      }
      return {
        ...prev,
        roles: {
          ...prev.roles,
          [roleId]: next as ModelCenterConfig["roles"][string]
        }
      };
    });
  }

  function updateRuntimeField(field: "max_retries" | "timeout", value: string) {
    setModelCenter((prev) => {
      if (!prev) return prev;
      const parsed = Number(value);
      return {
        ...prev,
        runtime: {
          ...prev.runtime,
          [field]: Number.isFinite(parsed) ? parsed : 0
        }
      };
    });
  }

  async function saveModelCenter() {
    if (!activeProject || !modelCenter) return;
    setSavingModelCenter(true);
    setError("");
    try {
      const saved = await updateModelCenter(activeProject.id, modelCenter);
      setModelCenter(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存模型配置失败");
    } finally {
      setSavingModelCenter(false);
    }
  }

  async function setConsistencyIssueStatus(issueId: number, status: ConsistencyIssueStatus) {
    if (!activeProject) return;
    setUpdatingIssueId(issueId);
    setError("");
    try {
      await updateConsistencyIssueStatus(activeProject.id, issueId, status);
      await refreshConsistency(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新一致性问题状态失败");
    } finally {
      setUpdatingIssueId(null);
    }
  }

  async function queueOpenErrorReprocess() {
    if (!activeProject) return;
    setBatchReprocessBusy(true);
    setBatchReprocessHint("");
    setError("");
    try {
      const result = await enqueueConsistencyOpenErrorReprocess(activeProject.id, {
        days: 90,
        maxChapters: 30,
        skipIfBusy: true
      });
      const queuedChapters = result.queued_jobs
        .map((job) => {
          const raw = job.payload?.chapter_number;
          const value = typeof raw === "number" ? raw : Number(raw);
          return Number.isFinite(value) && value > 0 ? value : null;
        })
        .filter((v): v is number => v != null);
      if (result.queued_jobs.length > 0) {
        const chapterHint = queuedChapters.length ? `（第 ${queuedChapters.join("、")} 章）` : "";
        const skippedHint = result.skipped_chapters.length
          ? `，跳过 ${result.skipped_chapters.length} 章（已有运行或排队任务）`
          : "";
        const truncHint = result.truncated ? "，结果过多已按上限截断" : "";
        setBatchReprocessHint(
          `已排队 ${result.queued_jobs.length} 个 reprocess 任务${chapterHint}${skippedHint}${truncHint}。`
        );
      } else if (result.matched_chapters.length > 0) {
        const truncHint = result.truncated ? "（命中章节过多，已按上限筛选）" : "";
        setBatchReprocessHint(
          `命中 ${result.matched_chapters.length} 个章节，但都已在任务队列中，未新增任务${truncHint}。`
        );
      } else {
        setBatchReprocessHint("当前没有 open + error 的一致性问题章节。");
      }
      await refreshJobs(activeProject.id);
      await refreshConsistency(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量提交重处理失败");
    } finally {
      setBatchReprocessBusy(false);
    }
  }

  async function jumpToIssue(issueId: number) {
    if (!activeProject) return;
    setError("");
    try {
      const jump = await getConsistencyIssueJump(activeProject.id, issueId);
      const hint = `${jump.chapter_file_path}${jump.line_hint ? ` (约第 ${jump.line_hint} 行)` : ""}`;
      setIssueJumpHints((prev) => ({ ...prev, [issueId]: hint }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "定位章节失败");
    }
  }

  async function controlJob(jobId: string, action: "cancel" | "pause" | "resume") {
    if (!activeProject) return;
    setJobActionLoadingId(jobId);
    setError("");
    try {
      if (action === "cancel") {
        await cancelJob(jobId);
      } else if (action === "pause") {
        await pauseJob(jobId);
      } else {
        await resumeJob(jobId);
      }
      await refreshJobs(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务控制失败");
    } finally {
      setJobActionLoadingId(null);
    }
  }

  async function createSnapshotNow() {
    if (!activeProject) return;
    const chapter = Number(snapshotChapterNumber);
    if (!Number.isFinite(chapter) || chapter <= 0) {
      setError("请输入有效章节号");
      return;
    }
    const tags = parseTagInput(snapshotCreateTags);
    setSnapshotBusy(true);
    setError("");
    try {
      await createSnapshot(activeProject.id, chapter, snapshotNote.trim(), tags);
      setSnapshotNote("");
      setSnapshotCreateTags("");
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建快照失败");
    } finally {
      setSnapshotBusy(false);
    }
  }

  async function restoreSnapshotNow(snapshotId: number, reprocess: boolean) {
    if (!activeProject) return;
    const tip = reprocess
      ? "恢复后将自动加入 reprocess 任务，确认继续？"
      : "确认恢复到这个版本快照？";
    if (!window.confirm(tip)) return;
    setRestoringSnapshotId(snapshotId);
    setError("");
    try {
      await restoreSnapshot(activeProject.id, snapshotId, reprocess);
      await refreshJobs(activeProject.id);
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复快照失败");
    } finally {
      setRestoringSnapshotId(null);
    }
  }

  async function loadSnapshotDiff(snapshotId: number) {
    if (!activeProject) return;
    setLoadingDiffSnapshotId(snapshotId);
    setError("");
    try {
      const diff = await getSnapshotDiff(activeProject.id, snapshotId, 2);
      setSnapshotDiff(diff);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取快照差异失败");
    } finally {
      setLoadingDiffSnapshotId(null);
    }
  }

  async function toggleSnapshotFavorite(snapshot: ChapterSnapshot) {
    if (!activeProject) return;
    setUpdatingSnapshotId(snapshot.id);
    setError("");
    try {
      await updateSnapshot(activeProject.id, snapshot.id, {
        isFavorite: !snapshot.is_favorite
      });
      await refreshSnapshots(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新快照收藏状态失败");
    } finally {
      setUpdatingSnapshotId(null);
    }
  }

  const runningJobs = jobs.filter((j) => j.status === "running").length;
  const failedJobs = jobs.filter((j) => j.status === "failed").length;
  const completedJobs = jobs.filter((j) => j.status === "completed").length;
  const estimatedUsd = costSummary?.cost_estimate_usd ?? 0;
  const consistencyOpen = consistencySummary?.open_count ?? 0;
  const consistencyErrors = consistencySummary?.error_count ?? 0;
  const importDisabledReason = useMemo(() => {
    if (importingProject) {
      return "正在导入中，请稍候...";
    }
    if (!activeProject) {
      return "请先在左侧选择或创建一个项目。";
    }
    if (!importSourceRoot.trim()) {
      return "请先选择要导入的小说根目录。";
    }
    return "";
  }, [importingProject, activeProject, importSourceRoot]);
  const importButtonDisabled = importDisabledReason.length > 0;

  return (
    <div className="app-shell">
      <aside className="bookshelf">
        <header className="panel-header">
          <h1>书架</h1>
          <p>{statusHint}</p>
        </header>
        <form className="new-project-form" onSubmit={onCreateProject}>
          <input
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="新书项目名称"
          />
          <button type="submit">创建</button>
        </form>
        <section className="import-panel">
          <div className="project-meta">导入已有小说到当前项目</div>
          <div className="import-row">
            <input
              value={importSourceRoot}
              onChange={(e) => setImportSourceRoot(e.target.value)}
              placeholder="选择你的旧小说根目录"
            />
            <button type="button" className="ghost-btn" onClick={chooseImportSourceDir}>
              选择目录
            </button>
          </div>
          <div className="import-flags">
            <label>
              <input
                type="checkbox"
                checked={importDatabase}
                onChange={(e) => setImportDatabase(e.target.checked)}
              />
              <span>导入数据库</span>
            </label>
            <label>
              <input
                type="checkbox"
                checked={importLightrag}
                onChange={(e) => setImportLightrag(e.target.checked)}
              />
              <span>导入 LightRAG</span>
            </label>
          </div>
          <button
            type="button"
            onClick={importIntoActiveProject}
            disabled={importButtonDisabled}
          >
            {importingProject ? "导入中..." : "导入到当前项目"}
          </button>
          <p className={`import-note ${importButtonDisabled ? "import-note-warning" : ""}`}>
            {importDisabledReason || "提示：导入会复制文件到当前项目工作区，不会修改原目录。"}
          </p>
          {importHint && <p className="import-note">{importHint}</p>}
        </section>
        <div className="project-list">
          {projects.map((project) => (
            <button
              type="button"
              key={project.id}
              className={`project-card ${project.id === activeProjectId ? "is-active" : ""}`}
              onClick={() => onActivate(project.id)}
            >
              <div className="project-title">{project.name}</div>
              <div className="project-meta">{project.slug}</div>
              <div className="project-meta">{project.is_active ? "当前项目" : "点击切换"}</div>
            </button>
          ))}
          {!projects.length && <div className="empty-note">还没有项目，先创建一本书。</div>}
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-hero">
          <div>
            <h2>AI-Novel 桌面工作台</h2>
            <p>清晰、轻松、可控的多书生成体验。</p>
          </div>
          <button type="button" className="hero-btn" onClick={queueInitProject} disabled={!activeProject}>
            初始化当前项目
          </button>
        </header>

        <section className="summary-grid">
          <article className="summary-card">
            <h3>当前项目</h3>
            <p className="big">{activeProject ? activeProject.name : "未选择"}</p>
            <small>{activeProject ? activeProject.workspace_dir : "创建或选择项目后开始写作"}</small>
          </article>
          <article className="summary-card">
            <h3>运行中任务</h3>
            <p className="big">{runningJobs}</p>
            <small>失败 {failedJobs} / 完成 {completedJobs}</small>
          </article>
          <article className="summary-card">
            <h3>下一步建议</h3>
            <p className="big">{activeProject ? "继续写这一章" : "先创建项目"}</p>
            <small>建议先执行一次初始化，然后再提交章节生成任务。</small>
          </article>
          <article className="summary-card">
            <h3>近30天预计成本</h3>
            <p className="big">${estimatedUsd.toFixed(3)}</p>
            <small>
              调用 {costSummary?.calls ?? 0} 次，输入 {costSummary?.input_tokens ?? 0} / 输出{" "}
              {costSummary?.output_tokens ?? 0} tokens
            </small>
          </article>
        </section>

        <section className="jobs-panel help-panel">
          <div className="panel-topline">
            <h3>Help</h3>
            <span className="box-note">常见操作提示</span>
          </div>
          <ul className="help-list">
            <li>先在左侧创建并选中一个项目，再提交写作、重处理和导入任务。</li>
            <li>导入旧书时请选择小说根目录（至少包含 chapters），建议勾选数据库与 LightRAG。</li>
            <li>手动改稿后请执行“提交 reprocess”，让状态库和检索索引重新同步。</li>
            <li>模型 API 更换入口在“模型配置中心”，保存后会立即作用于新任务。</li>
            <li>自动更新在应用启动时检查；有新版本会下载并提示是否重启安装。</li>
          </ul>
        </section>

        <section className="composer">
          <h3>提交单章生成任务</h3>
          <div className="composer-row">
            <input
              value={outlinePath}
              onChange={(e) => setOutlinePath(e.target.value)}
              placeholder="细纲文件路径，例如 C:/novel/outlines/第1章.md"
            />
            <input
              value={chapterNumber}
              onChange={(e) => setChapterNumber(e.target.value)}
              placeholder="章节号"
            />
            <button type="button" onClick={queueWriteChapter} disabled={!activeProject}>
              提交写作任务
            </button>
          </div>
          {error && <p className="error-note">{error}</p>}
        </section>

        <section className="composer">
          <h3>手动改稿后重处理</h3>
          <div className="composer-row composer-row-reprocess">
            <input
              value={reprocessChapterNumber}
              onChange={(e) => setReprocessChapterNumber(e.target.value)}
              placeholder="需要重处理的章节号"
            />
            <button
              type="button"
              onClick={() => queueReprocessChapter(reprocessChapterNumber)}
              disabled={!activeProject || reprocessBusy}
            >
              {reprocessBusy ? "提交中..." : "提交 reprocess"}
            </button>
          </div>
          <p className="box-note">用于你手动修改正文后，重新提取状态并刷新 LightRAG 索引。</p>
        </section>

        <section className="jobs-panel">
          <h3>任务队列</h3>
          <div className="jobs-list">
            {jobs.map((job) => (
              <article key={job.id} className={`job-item status-${job.status}`}>
                <div className="job-head">
                  <span>{job.job_type}</span>
                  <span>{job.status}</span>
                </div>
                <div className="job-meta">
                  <span>{job.current_stage ?? "待执行"}</span>
                  <span>
                    {job.current_chapter ? `第${job.current_chapter}章` : "—"}
                  </span>
                </div>
                <div className="job-actions-row">
                  {(job.status === "queued" || job.status === "running") && (
                    <button
                      type="button"
                      className="ghost-btn"
                      disabled={jobActionLoadingId === job.id}
                      onClick={() => controlJob(job.id, "cancel")}
                    >
                      {job.status === "running" ? "软取消" : "取消"}
                    </button>
                  )}
                  {job.status === "running" && job.job_type === "batch_write" && (
                    <>
                      {String(job.current_stage ?? "").startsWith("stage:paused") ||
                      String(job.current_stage ?? "") === "stage:pause_requested" ? (
                        <button
                          type="button"
                          className="ghost-btn"
                          disabled={jobActionLoadingId === job.id}
                          onClick={() => controlJob(job.id, "resume")}
                        >
                          继续
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="ghost-btn"
                          disabled={jobActionLoadingId === job.id}
                          onClick={() => controlJob(job.id, "pause")}
                        >
                          暂停
                        </button>
                      )}
                    </>
                  )}
                </div>
                {job.error && <p className="job-error">{job.error}</p>}
              </article>
            ))}
            {!jobs.length && <div className="empty-note">当前项目还没有任务。</div>}
          </div>
        </section>

        <section className="jobs-panel">
          <h3>成本明细（最近调用）</h3>
          <div className="jobs-list">
            {usageEvents.map((event) => (
              <article key={event.id} className="job-item">
                <div className="job-head">
                  <span>{event.model}</span>
                  <span>${event.cost_estimate_usd.toFixed(4)}</span>
                </div>
                <div className="job-meta">
                  <span>{event.stage ?? "stage:unknown"}</span>
                  <span>
                    in {event.input_tokens} / out {event.output_tokens}
                  </span>
                </div>
              </article>
            ))}
            {!usageEvents.length && <div className="empty-note">当前还没有成本数据。</div>}
          </div>
        </section>

        <section className="jobs-panel">
          <div className="panel-topline">
            <h3>一致性中心</h3>
            <div className="consistency-toolbar">
              <div className="consistency-filters">
                <select
                  value={consistencyStatusFilter}
                  onChange={(e) =>
                    setConsistencyStatusFilter(e.target.value as ConsistencyIssueStatus | "all")
                  }
                >
                  {ISSUE_STATUS_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <select
                  value={consistencySeverityFilter}
                  onChange={(e) => setConsistencySeverityFilter(e.target.value as "all" | "error" | "warning")}
                >
                  <option value="all">全部级别</option>
                  <option value="error">仅 error</option>
                  <option value="warning">仅 warning</option>
                </select>
                <input
                  className="consistency-inline-input"
                  value={consistencyChapterFilter}
                  onChange={(e) => setConsistencyChapterFilter(e.target.value)}
                  placeholder="章节号筛选"
                />
              </div>
              <button
                type="button"
                className="ghost-btn"
                disabled={!activeProject || batchReprocessBusy}
                onClick={queueOpenErrorReprocess}
              >
                {batchReprocessBusy ? "处理中..." : "一键重处理 Open Error"}
              </button>
            </div>
          </div>
          <div className="consistency-summary-row">
            <span className="consistency-pill">待处理 {consistencyOpen}</span>
            <span className="consistency-pill is-error">Error {consistencyErrors}</span>
            <span className="consistency-pill">已解决 {consistencySummary?.resolved_count ?? 0}</span>
            <span className="consistency-pill">已忽略 {consistencySummary?.ignored_count ?? 0}</span>
          </div>
          {!!consistencySummary?.by_type?.length && (
            <div className="consistency-type-row">
              {consistencySummary.by_type.slice(0, 6).map((item) => (
                <span key={item.issue_type} className="consistency-pill">
                  {issueTypeLabel(item.issue_type)} {item.count}
                </span>
              ))}
            </div>
          )}
          {batchReprocessHint && <p className="batch-note">{batchReprocessHint}</p>}
          <div className="jobs-list">
            {consistencyIssues.map((issue) => (
              <article key={issue.id} className={`job-item consistency-item severity-${issue.severity}`}>
                <div className="job-head">
                  <span>
                    第{issue.chapter_number ?? "?"}章 · {issueTypeLabel(issue.issue_type)}
                  </span>
                  <span className={`severity-tag severity-${issue.severity}`}>{issue.severity}</span>
                </div>
                <p className="consistency-desc">{issue.description}</p>
                <div className="job-meta">
                  <span>位置：{issue.location || "未标注"}</span>
                  <span>状态：{issue.status}</span>
                </div>
                {issue.fix_instruction && <p className="consistency-fix">建议：{issue.fix_instruction}</p>}
                <div className="consistency-actions">
                  <button type="button" className="ghost-btn" onClick={() => jumpToIssue(issue.id)}>
                    定位章节
                  </button>
                  {issue.chapter_number ? (
                    <button
                      type="button"
                      className="ghost-btn"
                      disabled={reprocessBusy}
                      onClick={() => queueReprocessChapter(String(issue.chapter_number))}
                    >
                      重处理本章
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={updatingIssueId === issue.id || issue.status === "open"}
                    onClick={() => setConsistencyIssueStatus(issue.id, "open")}
                  >
                    标记待处理
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={updatingIssueId === issue.id || issue.status === "resolved"}
                    onClick={() => setConsistencyIssueStatus(issue.id, "resolved")}
                  >
                    标记已解决
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={updatingIssueId === issue.id || issue.status === "ignored"}
                    onClick={() => setConsistencyIssueStatus(issue.id, "ignored")}
                  >
                    忽略
                  </button>
                </div>
                {issueJumpHints[issue.id] && <p className="jump-note">定位：{issueJumpHints[issue.id]}</p>}
              </article>
            ))}
            {!consistencyIssues.length && <div className="empty-note">最近没有匹配筛选条件的一致性问题。</div>}
          </div>
        </section>

        <section className="jobs-panel">
          <div className="panel-topline">
            <h3>版本快照</h3>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => activeProject && refreshSnapshots(activeProject.id)}
              disabled={!activeProject}
            >
              刷新
            </button>
          </div>
          <div className="snapshot-toolbar">
            <input
              value={snapshotChapterNumber}
              onChange={(e) => setSnapshotChapterNumber(e.target.value)}
              placeholder="章节号"
            />
            <input
              value={snapshotNote}
              onChange={(e) => setSnapshotNote(e.target.value)}
              placeholder="快照备注（可选）"
            />
            <input
              value={snapshotCreateTags}
              onChange={(e) => setSnapshotCreateTags(e.target.value)}
              placeholder="标签（逗号分隔，如 关键节点,改稿前）"
            />
            <button type="button" onClick={createSnapshotNow} disabled={!activeProject || snapshotBusy}>
              {snapshotBusy ? "创建中..." : "创建快照"}
            </button>
          </div>
          <div className="snapshot-search-row">
            <input
              value={snapshotSearchQuery}
              onChange={(e) => setSnapshotSearchQuery(e.target.value)}
              placeholder="关键词检索（标题/备注/路径/标签）"
            />
            <input
              value={snapshotFilterTags}
              onChange={(e) => setSnapshotFilterTags(e.target.value)}
              placeholder="按标签筛选（逗号分隔）"
            />
            <label className="snapshot-favorite-toggle">
              <input
                type="checkbox"
                checked={snapshotFavoritesOnly}
                onChange={(e) => setSnapshotFavoritesOnly(e.target.checked)}
              />
              <span>仅看收藏</span>
            </label>
          </div>
          {!!snapshotChapterSummary.length && (
            <div className="snapshot-timeline-row">
              {snapshotChapterSummary.map((item) => (
                <button
                  type="button"
                  key={`timeline-${item.chapter}`}
                  className={`timeline-chip ${String(item.chapter) === snapshotChapterNumber ? "is-active" : ""}`}
                  onClick={() => setSnapshotChapterNumber(String(item.chapter))}
                >
                  第{item.chapter}章 · {item.count}
                  {item.favorites > 0 ? ` · ★${item.favorites}` : ""}
                </button>
              ))}
            </div>
          )}
          <div className="jobs-list">
            {snapshots.map((snapshot) => (
              <article key={snapshot.id} className="job-item snapshot-item">
                <div className="job-head">
                  <span>
                    第{snapshot.chapter_number}章 · {snapshot.source_type}
                  </span>
                  <span>{snapshot.created_at}</span>
                </div>
                <div className="snapshot-meta">{snapshot.chapter_title || "无标题"}</div>
                {snapshot.note && <div className="snapshot-meta">备注：{snapshot.note}</div>}
                {snapshot.is_favorite && <div className="snapshot-meta">★ 收藏快照</div>}
                {!!snapshot.tags?.length && (
                  <div className="snapshot-tags">
                    {snapshot.tags.map((tag) => (
                      <span key={`${snapshot.id}-${tag}`} className="snapshot-tag-chip">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                <div className="snapshot-meta">{snapshot.snapshot_path}</div>
                <div className="snapshot-actions">
                  <button
                    type="button"
                    className={`ghost-btn ${snapshot.is_favorite ? "is-favorite" : ""}`}
                    disabled={updatingSnapshotId === snapshot.id}
                    onClick={() => toggleSnapshotFavorite(snapshot)}
                  >
                    {updatingSnapshotId === snapshot.id
                      ? "更新中..."
                      : snapshot.is_favorite
                        ? "取消收藏"
                        : "收藏"}
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={loadingDiffSnapshotId === snapshot.id}
                    onClick={() => loadSnapshotDiff(snapshot.id)}
                  >
                    {loadingDiffSnapshotId === snapshot.id ? "加载差异..." : "查看差异"}
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={restoringSnapshotId === snapshot.id}
                    onClick={() => restoreSnapshotNow(snapshot.id, false)}
                  >
                    恢复
                  </button>
                  <button
                    type="button"
                    className="ghost-btn"
                    disabled={restoringSnapshotId === snapshot.id}
                    onClick={() => restoreSnapshotNow(snapshot.id, true)}
                  >
                    恢复并重处理
                  </button>
                </div>
              </article>
            ))}
            {!snapshots.length && <div className="empty-note">当前章节暂无快照。</div>}
          </div>
          {snapshotDiff && (
            <div className="snapshot-diff-panel">
              <div className="snapshot-diff-head">
                <strong>
                  差异预览 · 快照 #{snapshotDiff.snapshot.id}（第{snapshotDiff.snapshot.chapter_number}章）
                </strong>
                <span>{snapshotDiff.has_changes ? "检测到变更" : "与当前正文一致"}</span>
              </div>
              <div className="snapshot-meta">{snapshotDiff.current_chapter_file}</div>
              {snapshotDiff.diff_lines.length ? (
                <pre className="diff-block">
                  {snapshotDiff.diff_lines.map((line, idx) => {
                    const cls =
                      line.startsWith("+") && !line.startsWith("+++")
                        ? "diff-line-add"
                        : line.startsWith("-") && !line.startsWith("---")
                          ? "diff-line-del"
                          : line.startsWith("@@")
                            ? "diff-line-hunk"
                            : "diff-line-ctx";
                    return (
                      <span className={cls} key={`${idx}-${line}`}>
                        {line}
                        {"\n"}
                      </span>
                    );
                  })}
                </pre>
              ) : (
                <div className="empty-note">无差异内容可展示。</div>
              )}
            </div>
          )}
        </section>

        <section className="jobs-panel">
          <div className="panel-topline">
            <h3>模型配置中心</h3>
            <button type="button" onClick={saveModelCenter} disabled={!modelCenter || savingModelCenter}>
              {savingModelCenter ? "保存中..." : "保存模型配置"}
            </button>
          </div>
          {!modelCenter ? (
            <div className="empty-note">请选择项目后加载模型配置。</div>
          ) : (
            <div className="model-center-grid">
              <article className="model-box model-box-wide">
                <div className="model-box-head">
                  <h4>Provider 配置池</h4>
                  <p className="box-note">先维护供应商池，再把角色绑定到目标 Provider。</p>
                </div>
                <div className="provider-add-row">
                  <input
                    value={newProviderId}
                    onChange={(e) => setNewProviderId(e.target.value)}
                    placeholder="provider_id（如 my_claude_1）"
                  />
                  <select
                    value={newProviderKind}
                    onChange={(e) => setNewProviderKind(e.target.value as (typeof PROVIDER_KIND_OPTIONS)[number])}
                  >
                    {PROVIDER_KIND_OPTIONS.map((kind) => (
                      <option key={kind} value={kind}>
                        {kind}
                      </option>
                    ))}
                  </select>
                  <button type="button" onClick={addProvider}>
                    新增 Provider
                  </button>
                </div>
                <div className="provider-list">
                  {providerIds.map((providerId) => {
                    const provider = modelCenter.providers[providerId];
                    const boundRoles = roleEntries
                      .filter(([, role]) => role.provider === providerId)
                      .map(([roleId]) => roleLabel(roleId));
                    return (
                      <article className="provider-card" key={providerId}>
                        <div className="provider-head">
                          <div>
                            <div className="provider-id">{providerId}</div>
                            <div className="provider-bound">
                              {boundRoles.length ? `绑定角色：${boundRoles.join(" / ")}` : "未绑定角色"}
                            </div>
                          </div>
                          <button type="button" className="ghost-btn" onClick={() => removeProvider(providerId)}>
                            删除
                          </button>
                        </div>
                        <div className="provider-fields">
                          <label className="field-stack">
                            <span>kind</span>
                            <select
                              value={provider.kind ?? "custom"}
                              onChange={(e) => updateProviderField(providerId, "kind", e.target.value)}
                            >
                              {PROVIDER_KIND_OPTIONS.map((kind) => (
                                <option key={kind} value={kind}>
                                  {kind}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field-stack">
                            <span>base_url</span>
                            <input
                              value={provider.base_url ?? ""}
                              onChange={(e) => updateProviderField(providerId, "base_url", e.target.value)}
                              placeholder="https://..."
                            />
                          </label>
                          <label className="field-stack field-stack-key">
                            <span>api_key</span>
                            <div className="inline-field-row">
                              <input
                                type={visibleProviderKeys[providerId] ? "text" : "password"}
                                value={provider.api_key ?? ""}
                                onChange={(e) => updateProviderField(providerId, "api_key", e.target.value)}
                                placeholder="sk-..."
                              />
                              <button
                                type="button"
                                className="mini-btn"
                                onClick={() => toggleProviderKeyVisible(providerId)}
                              >
                                {visibleProviderKeys[providerId] ? "隐藏" : "显示"}
                              </button>
                            </div>
                          </label>
                        </div>
                      </article>
                    );
                  })}
                  {!providerIds.length && <div className="empty-note">还没有 Provider，请先新增一个。</div>}
                </div>
              </article>

              <article className="model-box">
                <div className="model-box-head">
                  <h4>角色绑定与参数</h4>
                  <p className="box-note">角色绑定可独立切换，写作与分析可分流到不同渠道。</p>
                </div>
                <div className="roles-grid">
                  {roleEntries.map(([roleId, role]) => (
                    <article className="role-card" key={roleId}>
                      <div className="role-head">
                        <strong>{roleLabel(roleId)}</strong>
                        <span>{ROLE_HINTS[roleId] ?? "自定义角色"}</span>
                      </div>
                      <label className="field-stack">
                        <span>provider</span>
                        <select
                          value={role.provider ?? ""}
                          onChange={(e) => updateRoleProvider(roleId, e.target.value)}
                        >
                          <option value="">未选择</option>
                          {providerIds.map((providerId) => (
                            <option key={providerId} value={providerId}>
                              {providerId}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field-stack">
                        <span>model</span>
                        <input
                          value={role.model ?? ""}
                          onChange={(e) => updateRoleField(roleId, "model", e.target.value)}
                          placeholder="model id"
                        />
                      </label>
                      {shouldShowRoleField(roleId, role, "temperature") && (
                        <label className="field-stack">
                          <span>temperature</span>
                          <input
                            type="number"
                            step="0.1"
                            value={String(role.temperature ?? "")}
                            onChange={(e) => updateRoleField(roleId, "temperature", e.target.value)}
                            placeholder="0.0 - 1.0"
                          />
                        </label>
                      )}
                      {shouldShowRoleField(roleId, role, "timeout") && (
                        <label className="field-stack">
                          <span>timeout</span>
                          <input
                            type="number"
                            value={String(role.timeout ?? "")}
                            onChange={(e) => updateRoleField(roleId, "timeout", e.target.value)}
                            placeholder="seconds"
                          />
                        </label>
                      )}
                      {shouldShowRoleField(roleId, role, "max_tokens") && (
                        <label className="field-stack">
                          <span>max_tokens</span>
                          <input
                            type="number"
                            value={String(role.max_tokens ?? "")}
                            onChange={(e) => updateRoleField(roleId, "max_tokens", e.target.value)}
                            placeholder="max tokens"
                          />
                        </label>
                      )}
                      {shouldShowRoleField(roleId, role, "dim") && (
                        <label className="field-stack">
                          <span>dim</span>
                          <input
                            type="number"
                            value={String(role.dim ?? "")}
                            onChange={(e) => updateRoleField(roleId, "dim", e.target.value)}
                            placeholder="embedding dim"
                          />
                        </label>
                      )}
                    </article>
                  ))}
                </div>
              </article>

              <article className="model-box">
                <div className="model-box-head">
                  <h4>运行策略</h4>
                  <p className="box-note">控制重试与超时，失败后会尝试 fallback 通道。</p>
                </div>
                <label className="field-stack">
                  <span>max_retries</span>
                  <input
                    value={String(modelCenter.runtime.max_retries ?? "")}
                    onChange={(e) => updateRuntimeField("max_retries", e.target.value)}
                    placeholder="max_retries"
                  />
                </label>
                <label className="field-stack">
                  <span>timeout (sec)</span>
                  <input
                    value={String(modelCenter.runtime.timeout ?? "")}
                    onChange={(e) => updateRuntimeField("timeout", e.target.value)}
                    placeholder="timeout (sec)"
                  />
                </label>
              </article>

              <article className="model-box">
                <div className="model-box-head">
                  <h4>配置提示</h4>
                </div>
                <p className="box-note">
                  1) 建议保留 `anthropic_primary`、`anthropic_analysis`、`anthropic_fallback` 三个通道。2)
                  角色只改绑定，不需要反复改 prompt。3) API key 默认隐藏，避免误暴露。
                </p>
              </article>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
