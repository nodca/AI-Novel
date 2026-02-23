"""Health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    active = request.app.state.store.get_active_project()
    return {
        "status": "ok",
        "active_project_id": active["id"] if active else None,
    }

