"""Job queue routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from desktop.backend.api.schemas import JobCreateRequest, JobInfo, JobListResponse

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.post("/projects/{project_id}/jobs", response_model=JobInfo)
def enqueue_job(request: Request, project_id: str, payload: JobCreateRequest) -> JobInfo:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    try:
        job = request.app.state.jobs.enqueue(project_id, payload.job_type, payload.payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobInfo(**job)


@router.get("/projects/{project_id}/jobs", response_model=JobListResponse)
def list_project_jobs(
    request: Request,
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> JobListResponse:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    jobs = request.app.state.store.list_jobs(project_id=project_id, limit=limit)
    return JobListResponse(items=[JobInfo(**job) for job in jobs])


@router.get("/jobs/{job_id}", response_model=JobInfo)
def get_job(request: Request, job_id: str) -> JobInfo:
    job = request.app.state.store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobInfo(**job)


@router.post("/jobs/{job_id}/retry", response_model=JobInfo)
def retry_job(request: Request, job_id: str) -> JobInfo:
    try:
        job = request.app.state.jobs.retry(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobInfo(**job)


@router.post("/jobs/{job_id}/cancel", response_model=JobInfo)
def cancel_job(request: Request, job_id: str) -> JobInfo:
    try:
        job = request.app.state.jobs.cancel(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobInfo(**job)


@router.post("/jobs/{job_id}/pause", response_model=JobInfo)
def pause_job(request: Request, job_id: str) -> JobInfo:
    try:
        job = request.app.state.jobs.pause(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobInfo(**job)


@router.post("/jobs/{job_id}/resume", response_model=JobInfo)
def resume_job(request: Request, job_id: str) -> JobInfo:
    try:
        job = request.app.state.jobs.resume(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobInfo(**job)
