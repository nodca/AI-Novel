"""Model configuration center routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from desktop.backend.api.model_center import model_center_to_config_patch, project_config_to_model_center
from desktop.backend.api.schemas import ModelCenterConfig

router = APIRouter(prefix="/api/v1/projects/{project_id}/model-center", tags=["model-center"])


def _ensure_project(request: Request, project_id: str) -> None:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


@router.get("", response_model=ModelCenterConfig)
def get_model_center(request: Request, project_id: str) -> ModelCenterConfig:
    _ensure_project(request, project_id)
    try:
        config = request.app.state.workspace.get_config(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = project_config_to_model_center(config)
    return ModelCenterConfig(**payload)


@router.put("", response_model=ModelCenterConfig)
def update_model_center(
    request: Request,
    project_id: str,
    payload: ModelCenterConfig,
) -> ModelCenterConfig:
    _ensure_project(request, project_id)
    try:
        patch = model_center_to_config_patch(payload.model_dump())
        merged = request.app.state.workspace.patch_config(project_id, patch)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized = project_config_to_model_center(merged)
    return ModelCenterConfig(**normalized)

