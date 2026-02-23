"""FastAPI entrypoint for desktop local control plane."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from desktop.backend.api.config import build_paths
from desktop.backend.api.job_manager import JobManager
from desktop.backend.api.routes_consistency import router as consistency_router
from desktop.backend.api.routes_costs import router as costs_router
from desktop.backend.api.routes_health import router as health_router
from desktop.backend.api.routes_jobs import router as jobs_router
from desktop.backend.api.routes_model_center import router as model_center_router
from desktop.backend.api.routes_projects import router as projects_router
from desktop.backend.api.routes_snapshots import router as snapshots_router
from desktop.backend.api.state_store import StateStore
from desktop.backend.api.workspace import WorkspaceService

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    paths = build_paths()
    store = StateStore(paths.state_db)
    workspace = WorkspaceService(paths, store)
    jobs = JobManager(store, workspace)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[override]
        logger.info("Starting desktop backend")
        jobs.start()
        try:
            yield
        finally:
            jobs.stop()
            logger.info("Stopped desktop backend")

    app = FastAPI(
        title="AI-Novel Desktop API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.paths = paths
    app.state.store = store
    app.state.workspace = workspace
    app.state.jobs = jobs

    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(jobs_router)
    app.include_router(costs_router)
    app.include_router(consistency_router)
    app.include_router(snapshots_router)
    app.include_router(model_center_router)
    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "desktop.backend.api.main:app",
        host="127.0.0.1",
        port=8008,
        reload=False,
    )


if __name__ == "__main__":
    run()
