"""Consistency center routes."""

from __future__ import annotations

import re
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query, Request

from desktop.backend.api.schemas import (
    ConsistencyBatchReprocessRequest,
    ConsistencyBatchReprocessResponse,
    ConsistencyIssueInfo,
    ConsistencyIssueJumpInfo,
    ConsistencyIssueListResponse,
    ConsistencyIssueStatusUpdateRequest,
    ConsistencySummaryResponse,
    JobInfo,
)

ALLOWED_STATUS = {"open", "resolved", "ignored"}
ALLOWED_SEVERITY = {"error", "warning"}

router = APIRouter(prefix="/api/v1/projects/{project_id}/consistency", tags=["consistency"])


def _ensure_project_exists(request: Request, project_id: str) -> None:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_values(values: Iterable[str], allowed: set[str], field: str) -> list[str]:
    out = []
    for item in values:
        if item not in allowed:
            raise HTTPException(status_code=400, detail=f"Invalid {field}: {item}")
        out.append(item)
    return out


def _extract_scene_number(location: str) -> int | None:
    if not location:
        return None
    match = re.search(r"scene_(\d+)", location)
    if not match:
        return None
    try:
        num = int(match.group(1))
    except ValueError:
        return None
    return num if num > 0 else None


def _line_hint_for_scene(chapter_file_path: str, scene_number: int | None) -> int | None:
    if not scene_number:
        return 1
    try:
        with open(chapter_file_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None

    if scene_number <= 1:
        return 1
    delimiters_seen = 0
    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("---"):
            delimiters_seen += 1
            if delimiters_seen >= scene_number - 1:
                return min(idx + 1, max(1, len(lines)))
    return max(1, len(lines))


@router.get("/summary", response_model=ConsistencySummaryResponse)
def consistency_summary(
    request: Request,
    project_id: str,
    days: int = Query(default=90, ge=1, le=365),
) -> ConsistencySummaryResponse:
    _ensure_project_exists(request, project_id)
    payload = request.app.state.store.get_consistency_summary(project_id, days=days)
    return ConsistencySummaryResponse(**payload)


@router.get("/issues", response_model=ConsistencyIssueListResponse)
def list_consistency_issues(
    request: Request,
    project_id: str,
    days: int = Query(default=90, ge=1, le=365),
    limit: int = Query(default=200, ge=1, le=500),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    chapter_number: int | None = Query(default=None, ge=1),
) -> ConsistencyIssueListResponse:
    _ensure_project_exists(request, project_id)
    statuses = _validate_values(_split_csv(status), ALLOWED_STATUS, "status")
    severities = _validate_values(_split_csv(severity), ALLOWED_SEVERITY, "severity")
    items = request.app.state.store.list_consistency_issues(
        project_id,
        limit=limit,
        days=days,
        statuses=statuses,
        severities=severities,
        chapter_number=chapter_number,
    )
    return ConsistencyIssueListResponse(items=[ConsistencyIssueInfo(**item) for item in items])


@router.post("/reprocess-open-errors", response_model=ConsistencyBatchReprocessResponse)
def reprocess_open_errors(
    request: Request,
    project_id: str,
    payload: ConsistencyBatchReprocessRequest,
) -> ConsistencyBatchReprocessResponse:
    _ensure_project_exists(request, project_id)
    issues = request.app.state.store.list_consistency_issues(
        project_id,
        limit=500,
        days=payload.days,
        statuses=["open"],
        severities=["error"],
    )

    chapter_set: set[int] = set()
    for issue in issues:
        raw_chapter = issue.get("chapter_number")
        try:
            chapter = int(raw_chapter)
        except (TypeError, ValueError):
            continue
        if chapter > 0:
            chapter_set.add(chapter)

    all_matched_chapters = sorted(chapter_set)
    matched_chapters = all_matched_chapters[: payload.max_chapters]
    truncated = len(all_matched_chapters) > len(matched_chapters)

    busy_chapters: set[int] = set()
    if payload.skip_if_busy:
        existing = request.app.state.store.list_jobs(
            project_id=project_id,
            statuses=("queued", "running"),
            limit=500,
        )
        for job in existing:
            if job.get("job_type") != "reprocess":
                continue
            raw_chapter = (job.get("payload") or {}).get("chapter_number")
            try:
                chapter = int(raw_chapter)
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                busy_chapters.add(chapter)

    queued_jobs: list[JobInfo] = []
    skipped_chapters: list[int] = []
    for chapter in matched_chapters:
        if chapter in busy_chapters:
            skipped_chapters.append(chapter)
            continue
        queued = request.app.state.jobs.enqueue(
            project_id=project_id,
            job_type="reprocess",
            payload={
                "chapter_number": chapter,
                "source": "consistency_open_error_batch",
            },
        )
        queued_jobs.append(JobInfo(**queued))
        busy_chapters.add(chapter)

    return ConsistencyBatchReprocessResponse(
        project_id=project_id,
        period_days=payload.days,
        matched_issue_count=len(issues),
        matched_chapters=matched_chapters,
        queued_jobs=queued_jobs,
        skipped_chapters=skipped_chapters,
        truncated=truncated,
    )


@router.patch("/issues/{issue_id}", response_model=ConsistencyIssueInfo)
def update_consistency_issue_status(
    request: Request,
    project_id: str,
    issue_id: int,
    payload: ConsistencyIssueStatusUpdateRequest,
) -> ConsistencyIssueInfo:
    _ensure_project_exists(request, project_id)
    updated = request.app.state.store.update_consistency_issue_status(
        project_id=project_id,
        issue_id=issue_id,
        status=payload.status,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Consistency issue {issue_id} not found")
    return ConsistencyIssueInfo(**updated)


@router.get("/issues/{issue_id}/jump", response_model=ConsistencyIssueJumpInfo)
def consistency_issue_jump(
    request: Request,
    project_id: str,
    issue_id: int,
) -> ConsistencyIssueJumpInfo:
    _ensure_project_exists(request, project_id)
    issue = request.app.state.store.get_consistency_issue(project_id, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Consistency issue {issue_id} not found")
    chapter_number = issue.get("chapter_number")
    if not chapter_number:
        raise HTTPException(status_code=400, detail="Issue has no chapter_number, cannot jump")

    chapter_file = request.app.state.workspace.find_chapter_file(project_id, int(chapter_number))
    if not chapter_file:
        raise HTTPException(status_code=404, detail=f"Chapter file for chapter {chapter_number} not found")

    scene_number = _extract_scene_number(issue.get("location", ""))
    line_hint = _line_hint_for_scene(str(chapter_file), scene_number)
    return ConsistencyIssueJumpInfo(
        issue=ConsistencyIssueInfo(**issue),
        chapter_file_path=str(chapter_file),
        scene_number=scene_number,
        line_hint=line_hint,
    )
