"""Adapter to execute existing AI-Novel pipeline from desktop jobs."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import yaml

from core.interrupts import GenerationCancelled
from core.pipeline import init_project, reprocess_chapter, run_chapter

ProgressCallback = Optional[Callable[[str, Optional[int]], None]]
UsageCallback = Optional[Callable[[Dict[str, Any]], None]]
ConsistencyCallback = Optional[Callable[[Dict[str, Any]], None]]
CancelCallback = Optional[Callable[[], bool]]
PauseCallback = Optional[Callable[[], bool]]


def _load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def run_engine_job(
    *,
    job_type: str,
    payload: Dict[str, Any],
    config_path: str,
    progress: ProgressCallback = None,
    usage_callback: UsageCallback = None,
    consistency_callback: ConsistencyCallback = None,
    should_cancel: CancelCallback = None,
    should_pause: PauseCallback = None,
    usage_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute one job against the existing generation engine."""
    config = _load_config(config_path)
    stage_state: Dict[str, Any] = {"stage": "stage:boot", "chapter": None}
    meta = usage_context or {}

    def _update_stage(stage: str, chapter: Optional[int]) -> None:
        stage_state["stage"] = stage
        stage_state["chapter"] = chapter
        if progress:
            progress(stage, chapter)

    def _check_cancel() -> None:
        if callable(should_cancel) and should_cancel():
            raise GenerationCancelled("Job canceled by user")

    def _wait_if_paused(chapter: Optional[int]) -> None:
        while callable(should_pause) and should_pause():
            _update_stage("stage:paused", chapter)
            _check_cancel()
            time.sleep(0.4)

    if usage_callback or consistency_callback:
        config["_telemetry"] = {
            "stage_state": stage_state,
            "project_id": meta.get("project_id"),
            "job_id": meta.get("job_id"),
            "job_type": job_type,
        }
        if usage_callback:
            config["_telemetry"]["usage_callback"] = usage_callback
        if consistency_callback:
            config["_telemetry"]["consistency_callback"] = consistency_callback

    if job_type == "init_project":
        _wait_if_paused(None)
        _check_cancel()
        _update_stage("stage:init", None)
        init_project(config, progress_callback=_update_stage)
        _check_cancel()
        return {"message": "Project initialized"}

    if job_type == "write_chapter":
        outline = str(payload.get("outline_path", "")).strip()
        chapter = int(payload.get("chapter_number"))
        if not outline:
            raise ValueError("payload.outline_path is required")
        _wait_if_paused(chapter)
        _check_cancel()
        _update_stage("stage:write", chapter)
        chapter_text = run_chapter(
            config,
            outline,
            chapter,
            auto_confirm=True,
            progress_callback=_update_stage,
            should_cancel=should_cancel,
            should_pause=should_pause,
        )
        _check_cancel()
        return {"chapter_number": chapter, "text_length": len(chapter_text or "")}

    if job_type == "batch_write":
        outline = str(payload.get("outline_path", "")).strip()
        start = int(payload.get("start"))
        end = int(payload.get("end"))
        if not outline:
            raise ValueError("payload.outline_path is required")
        if end < start:
            raise ValueError("payload.end must be greater than or equal to payload.start")

        completed = []
        for chapter in range(start, end + 1):
            _wait_if_paused(chapter)
            _check_cancel()
            _update_stage("stage:batch_write", chapter)
            run_chapter(
                config,
                outline,
                chapter,
                auto_confirm=True,
                progress_callback=_update_stage,
                should_cancel=should_cancel,
                should_pause=should_pause,
            )
            completed.append(chapter)
            _check_cancel()
        return {"chapters_completed": completed}

    if job_type == "reprocess":
        chapter = int(payload.get("chapter_number"))
        _wait_if_paused(chapter)
        _check_cancel()
        _update_stage("stage:reprocess", chapter)
        reprocess_chapter(config, chapter, progress_callback=_update_stage)
        _check_cancel()
        return {"chapter_number": chapter, "message": "Reprocess complete"}

    raise ValueError(f"Unsupported job_type: {job_type}")
