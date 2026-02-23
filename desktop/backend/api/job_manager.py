"""Background queue worker for desktop generation jobs."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.interrupts import GenerationCancelled
from desktop.backend.api.engine_adapter import run_engine_job
from desktop.backend.api.state_store import StateStore
from desktop.backend.api.workspace import WorkspaceService

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobManager:
    """Single worker queue manager for generation jobs."""

    def __init__(self, state: StateStore, workspace: WorkspaceService):
        self.state = state
        self.workspace = workspace
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._controls_lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}
        self._pause_events: Dict[str, threading.Event] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        for pending in self.state.list_jobs(statuses=("queued",), limit=500):
            self._queue.put(pending["id"])

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def enqueue(self, project_id: str, job_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = _utc_now_iso()
        job = self.state.create_job(
            {
                "id": uuid.uuid4().hex,
                "project_id": project_id,
                "job_type": job_type,
                "status": "queued",
                "payload": payload,
                "created_at": now,
                "updated_at": now,
            }
        )
        self._queue.put(job["id"])
        return job

    def retry(self, job_id: str) -> Dict[str, Any]:
        job = self.state.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job["status"] not in ("failed", "canceled"):
            raise ValueError("Only failed or canceled jobs can be retried")
        retried = self.enqueue(job["project_id"], job["job_type"], job["payload"])
        return retried

    def cancel(self, job_id: str) -> Dict[str, Any]:
        job = self.state.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job["status"] == "queued":
            updated = self.state.update_job(
                job_id,
                status="canceled",
                current_stage="stage:canceled",
            )
            if not updated:
                raise ValueError(f"Job {job_id} was not updated")
            return updated
        if job["status"] == "running":
            with self._controls_lock:
                evt = self._cancel_events.get(job_id)
            if not evt:
                raise ValueError("Running job is not yet controllable, please retry")
            evt.set()
            updated = self.state.update_job(
                job_id,
                current_stage="stage:cancel_requested",
            )
            if not updated:
                raise ValueError(f"Job {job_id} was not updated")
            return updated
        raise ValueError("Only queued or running jobs can be canceled")

    def pause(self, job_id: str) -> Dict[str, Any]:
        job = self.state.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job["status"] != "running":
            raise ValueError("Only running jobs can be paused")
        if job["job_type"] != "batch_write":
            raise ValueError("Pause/resume is only supported for batch_write jobs")
        with self._controls_lock:
            evt = self._pause_events.get(job_id)
        if not evt:
            raise ValueError("Running job is not yet controllable, please retry")
        evt.set()
        updated = self.state.update_job(
            job_id,
            current_stage="stage:pause_requested",
        )
        if not updated:
            raise ValueError(f"Job {job_id} was not updated")
        return updated

    def resume(self, job_id: str) -> Dict[str, Any]:
        job = self.state.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job["status"] != "running":
            raise ValueError("Only running jobs can be resumed")
        if job["job_type"] != "batch_write":
            raise ValueError("Pause/resume is only supported for batch_write jobs")
        with self._controls_lock:
            evt = self._pause_events.get(job_id)
        if not evt:
            raise ValueError("Running job is not yet controllable, please retry")
        evt.clear()
        updated = self.state.update_job(
            job_id,
            current_stage="stage:resume_requested",
        )
        if not updated:
            raise ValueError(f"Job {job_id} was not updated")
        return updated

    def _register_job_control(self, job_id: str) -> tuple[threading.Event, threading.Event]:
        cancel_evt = threading.Event()
        pause_evt = threading.Event()
        with self._controls_lock:
            self._cancel_events[job_id] = cancel_evt
            self._pause_events[job_id] = pause_evt
        return cancel_evt, pause_evt

    def _clear_job_control(self, job_id: str) -> None:
        with self._controls_lock:
            self._cancel_events.pop(job_id, None)
            self._pause_events.pop(job_id, None)

    @staticmethod
    def _resolve_reprocess_chapter(
        payload: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Optional[int]:
        for source in (result, payload):
            raw = source.get("chapter_number")
            try:
                chapter = int(raw)
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                return chapter
        return None

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._run_one(job_id)
            except Exception:  # pragma: no cover
                logger.exception("Worker loop crashed for job %s", job_id)
            finally:
                self._queue.task_done()

    def _run_one(self, job_id: str) -> None:
        job = self.state.get_job(job_id)
        if not job:
            return
        if job["status"] != "queued":
            return

        project = self.state.get_project(job["project_id"])
        if not project:
            self.state.update_job(
                job_id,
                status="failed",
                current_stage="stage:failed",
                error=f"Project {job['project_id']} not found",
            )
            return

        self.state.update_job(job_id, status="running", current_stage="stage:boot")
        cancel_evt, pause_evt = self._register_job_control(job_id)

        def _progress(stage: str, chapter: Optional[int]) -> None:
            self.state.update_job(
                job_id,
                current_stage=stage,
                current_chapter=chapter if chapter is not None else None,
            )

        def _usage(event: Dict[str, Any]) -> None:
            payload = dict(event)
            payload.setdefault("project_id", project["id"])
            payload.setdefault("job_id", job_id)
            self.state.add_usage_event(payload)

        def _consistency(event: Dict[str, Any]) -> None:
            phase = str(event.get("phase", "final")).strip().lower()
            if phase != "final":
                return
            chapter_number = event.get("chapter_number")
            issues = event.get("issues")
            if not isinstance(issues, list):
                return
            for item in issues:
                if not isinstance(item, dict):
                    continue
                self.state.upsert_consistency_issue(
                    {
                        "project_id": project["id"],
                        "job_id": job_id,
                        "chapter_number": chapter_number,
                        "issue_type": item.get("type", "unknown"),
                        "severity": item.get("severity", "warning"),
                        "description": item.get("description", ""),
                        "location": item.get("location", ""),
                        "fix_instruction": item.get("fix_instruction", ""),
                        "status": "open",
                        "phase": phase,
                    }
                )

        def _should_cancel() -> bool:
            return cancel_evt.is_set()

        def _should_pause() -> bool:
            return pause_evt.is_set()

        try:
            try:
                result = run_engine_job(
                    job_type=job["job_type"],
                    payload=job["payload"],
                    config_path=project["config_path"],
                    progress=_progress,
                    usage_callback=_usage,
                    consistency_callback=_consistency,
                    should_cancel=_should_cancel,
                    should_pause=_should_pause,
                    usage_context={"project_id": project["id"], "job_id": job_id},
                )
            except GenerationCancelled as exc:
                self.state.update_job(
                    job_id,
                    status="canceled",
                    current_stage="stage:canceled",
                    error=str(exc),
                )
                return

            if job["job_type"] == "reprocess":
                chapter = self._resolve_reprocess_chapter(job.get("payload", {}), result)
                if chapter:
                    resolved_count = self.state.resolve_open_consistency_issues_for_chapter(
                        project["id"],
                        chapter,
                    )
                    result = {
                        **result,
                        "auto_resolved_issue_count": int(resolved_count),
                        "auto_resolved_chapter": int(chapter),
                    }
                    if resolved_count > 0:
                        logger.info(
                            "Auto-resolved %s open consistency issues for chapter %s (project=%s, job=%s)",
                            resolved_count,
                            chapter,
                            project["id"],
                            job_id,
                        )

            self.state.update_job(
                job_id,
                status="completed",
                current_stage="stage:done",
                result=result,
                error=None,
            )
            self._auto_snapshot_after_success(project["id"], job["job_type"], result)
            self.state.touch_project(project["id"])
        except Exception as exc:
            self.state.update_job(
                job_id,
                status="failed",
                current_stage="stage:failed",
                error=str(exc),
            )
        finally:
            self._clear_job_control(job_id)

    def _auto_snapshot_after_success(self, project_id: str, job_type: str, result: Dict[str, Any]) -> None:
        chapters: list[int] = []
        if job_type == "write_chapter":
            try:
                chapters.append(int(result.get("chapter_number")))
            except (TypeError, ValueError):
                return
        elif job_type == "batch_write":
            raw = result.get("chapters_completed")
            if isinstance(raw, list):
                for item in raw:
                    try:
                        chapters.append(int(item))
                    except (TypeError, ValueError):
                        continue
        else:
            return

        for chapter in chapters:
            try:
                self.workspace.create_snapshot(
                    project_id,
                    chapter,
                    source_type="auto_write",
                    note="Auto snapshot after successful generation",
                )
            except Exception as exc:
                logger.warning("auto snapshot failed for chapter %s: %s", chapter, exc)
