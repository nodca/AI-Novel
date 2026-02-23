"""Cost and token analytics routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from desktop.backend.api.schemas import CostSummaryResponse, UsageEventInfo

router = APIRouter(prefix="/api/v1/projects/{project_id}/costs", tags=["costs"])


def _ensure_project_exists(request: Request, project_id: str) -> None:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


@router.get("/summary", response_model=CostSummaryResponse)
def cost_summary(
    request: Request,
    project_id: str,
    days: int = Query(default=30, ge=1, le=365),
) -> CostSummaryResponse:
    _ensure_project_exists(request, project_id)
    payload = request.app.state.store.get_cost_summary(project_id, days=days)
    return CostSummaryResponse(**payload)


@router.get("/events", response_model=list[UsageEventInfo])
def usage_events(
    request: Request,
    project_id: str,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=120, ge=1, le=500),
) -> list[UsageEventInfo]:
    _ensure_project_exists(request, project_id)
    events = request.app.state.store.list_usage_events(project_id, limit=limit, days=days)
    return [UsageEventInfo(**e) for e in events]

