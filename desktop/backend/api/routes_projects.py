"""Project/workspace routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from desktop.backend.api.schemas import (
    ProjectImportRequest,
    ProjectImportResponse,
    ProjectConfigPatchRequest,
    ProjectCreateRequest,
    ProjectInfo,
    ProjectListResponse,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(request: Request) -> ProjectListResponse:
    items = request.app.state.store.list_projects()
    return ProjectListResponse(items=[ProjectInfo(**item) for item in items])


@router.post("", response_model=ProjectInfo)
def create_project(request: Request, payload: ProjectCreateRequest) -> ProjectInfo:
    try:
        project = request.app.state.workspace.create_project(payload.name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectInfo(**project)


@router.post("/{project_id}/activate", response_model=ProjectInfo)
def activate_project(request: Request, project_id: str) -> ProjectInfo:
    project = request.app.state.workspace.activate(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectInfo(**project)


@router.get("/{project_id}", response_model=ProjectInfo)
def get_project(request: Request, project_id: str) -> ProjectInfo:
    project = request.app.state.store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectInfo(**project)


@router.get("/{project_id}/config")
def get_project_config(request: Request, project_id: str) -> dict:
    try:
        return request.app.state.workspace.get_config(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{project_id}/config")
def patch_project_config(
    request: Request,
    project_id: str,
    payload: ProjectConfigPatchRequest,
) -> dict:
    try:
        return request.app.state.workspace.patch_config(project_id, payload.patch)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/import", response_model=ProjectImportResponse)
def import_project_content(
    request: Request,
    project_id: str,
    payload: ProjectImportRequest,
) -> ProjectImportResponse:
    try:
        result = request.app.state.workspace.import_existing_content(
            project_id,
            source_root=payload.source_root,
            overwrite=payload.overwrite,
            import_database=payload.import_database,
            import_lightrag=payload.import_lightrag,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectImportResponse(**result)
