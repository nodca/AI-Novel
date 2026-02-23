"""Chapter version snapshots routes."""

from __future__ import annotations

import difflib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from desktop.backend.api.schemas import (
    ChapterSnapshotCreateRequest,
    ChapterSnapshotDiffResponse,
    ChapterSnapshotInfo,
    ChapterSnapshotListResponse,
    ChapterSnapshotPatchRequest,
    ChapterSnapshotRestoreRequest,
    ChapterSnapshotRestoreResponse,
    JobInfo,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/snapshots", tags=["snapshots"])


def _ensure_project_exists(request: Request, project_id: str) -> None:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


@router.get("", response_model=ChapterSnapshotListResponse)
def list_snapshots(
    request: Request,
    project_id: str,
    chapter_number: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    favorites_only: bool = Query(default=False),
    limit: int = Query(default=120, ge=1, le=500),
) -> ChapterSnapshotListResponse:
    _ensure_project_exists(request, project_id)
    rows = request.app.state.store.list_chapter_snapshots(
        project_id,
        chapter_number=chapter_number,
        query=q,
        tags=_split_csv(tags),
        favorites_only=favorites_only,
        limit=limit,
    )
    return ChapterSnapshotListResponse(items=[ChapterSnapshotInfo(**row) for row in rows])


@router.post("", response_model=ChapterSnapshotInfo)
def create_snapshot(
    request: Request,
    project_id: str,
    payload: ChapterSnapshotCreateRequest,
) -> ChapterSnapshotInfo:
    _ensure_project_exists(request, project_id)
    try:
        created = request.app.state.workspace.create_snapshot(
            project_id,
            payload.chapter_number,
            source_type="manual",
            note=payload.note or "",
            tags=payload.tags or [],
            is_favorite=payload.is_favorite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChapterSnapshotInfo(**created)


@router.patch("/{snapshot_id}", response_model=ChapterSnapshotInfo)
def patch_snapshot(
    request: Request,
    project_id: str,
    snapshot_id: int,
    payload: ChapterSnapshotPatchRequest,
) -> ChapterSnapshotInfo:
    _ensure_project_exists(request, project_id)
    updated = request.app.state.store.update_chapter_snapshot(
        project_id,
        snapshot_id,
        note=payload.note,
        tags=payload.tags,
        is_favorite=payload.is_favorite,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return ChapterSnapshotInfo(**updated)


@router.get("/{snapshot_id}/diff", response_model=ChapterSnapshotDiffResponse)
def snapshot_diff(
    request: Request,
    project_id: str,
    snapshot_id: int,
    context_lines: int = Query(default=2, ge=0, le=20),
) -> ChapterSnapshotDiffResponse:
    _ensure_project_exists(request, project_id)
    snapshot = request.app.state.store.get_chapter_snapshot(project_id, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    snapshot_path = Path(snapshot["snapshot_path"])
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail=f"Snapshot file not found: {snapshot_path}")

    chapter_number = int(snapshot["chapter_number"])
    current_path = request.app.state.workspace.find_chapter_file(project_id, chapter_number)
    if not current_path:
        fallback = Path(snapshot.get("chapter_file_path", ""))
        current_path = fallback if fallback.exists() else None
    if not current_path:
        raise HTTPException(status_code=404, detail=f"Current chapter file for chapter {chapter_number} not found")

    old_text = snapshot_path.read_text(encoding="utf-8").splitlines()
    new_text = current_path.read_text(encoding="utf-8").splitlines()
    diff_lines = list(
        difflib.unified_diff(
            old_text,
            new_text,
            fromfile=f"snapshot:{snapshot_path.name}",
            tofile=f"current:{current_path.name}",
            n=context_lines,
            lineterm="",
        )
    )
    return ChapterSnapshotDiffResponse(
        snapshot=ChapterSnapshotInfo(**snapshot),
        current_chapter_file=str(current_path),
        has_changes=old_text != new_text,
        diff_lines=diff_lines,
    )


@router.post("/{snapshot_id}/restore", response_model=ChapterSnapshotRestoreResponse)
def restore_snapshot(
    request: Request,
    project_id: str,
    snapshot_id: int,
    payload: ChapterSnapshotRestoreRequest,
) -> ChapterSnapshotRestoreResponse:
    _ensure_project_exists(request, project_id)
    try:
        restored = request.app.state.workspace.restore_snapshot(project_id, snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    queued_job = None
    if payload.reprocess:
        chapter_number = int(restored["snapshot"]["chapter_number"])
        queued = request.app.state.jobs.enqueue(
            project_id=project_id,
            job_type="reprocess",
            payload={"chapter_number": chapter_number},
        )
        queued_job = JobInfo(**queued)

    return ChapterSnapshotRestoreResponse(
        snapshot=ChapterSnapshotInfo(**restored["snapshot"]),
        restored_chapter_file=restored["restored_chapter_file"],
        backup_snapshot=ChapterSnapshotInfo(**restored["backup_snapshot"])
        if restored.get("backup_snapshot")
        else None,
        queued_reprocess_job=queued_job,
    )
