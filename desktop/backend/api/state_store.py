"""SQLite-backed state store for desktop metadata."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class StateStore:
    """Persistent app metadata store (projects, jobs)."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    workspace_dir TEXT NOT NULL UNIQUE,
                    config_path TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    current_stage TEXT,
                    current_chapter INTEGER,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_project_created
                    ON jobs(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_status
                    ON jobs(status);

                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    job_id TEXT,
                    chapter_number INTEGER,
                    stage TEXT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    cost_estimate_usd REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_usage_events_project_time
                    ON usage_events(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_project_model
                    ON usage_events(project_id, model);

                CREATE TABLE IF NOT EXISTS consistency_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    job_id TEXT,
                    chapter_number INTEGER,
                    issue_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location TEXT,
                    fix_instruction TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    phase TEXT NOT NULL DEFAULT 'final',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_consistency_project_time
                    ON consistency_issues(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_consistency_project_status
                    ON consistency_issues(project_id, status);
                CREATE INDEX IF NOT EXISTS idx_consistency_project_severity
                    ON consistency_issues(project_id, severity);

                CREATE TABLE IF NOT EXISTS chapter_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    chapter_title TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    note TEXT NOT NULL DEFAULT '',
                    chapter_file_path TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_project_chapter_time
                    ON chapter_snapshots(project_id, chapter_number, created_at DESC);
                """
            )
            self._ensure_column(
                conn,
                table="chapter_snapshots",
                column="tags_json",
                definition="TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                conn,
                table="chapter_snapshots",
                column="is_favorite",
                definition="INTEGER NOT NULL DEFAULT 0",
            )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        exists = any(str(row["name"]) == column for row in rows)
        if not exists:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _normalize_snapshot_tags(raw: Any) -> List[str]:
        if raw is None:
            return []

        values: List[str] = []
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, list):
                values = [str(item) for item in payload]
            else:
                values = text.replace("，", ",").split(",")
        elif isinstance(raw, (list, tuple, set)):
            values = [str(item) for item in raw]
        else:
            return []

        out: List[str] = []
        seen: set[str] = set()
        for item in values:
            tag = str(item).strip()
            if not tag:
                continue
            if len(tag) > 28:
                tag = tag[:28]
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(tag)
            if len(out) >= 12:
                break
        return out

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "slug": row["slug"],
            "workspace_dir": row["workspace_dir"],
            "config_path": row["config_path"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Dict[str, Any]:
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "job_type": row["job_type"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
            "current_stage": row["current_stage"],
            "current_chapter": row["current_chapter"],
            "result": result,
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_usage_event(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "project_id": row["project_id"],
            "job_id": row["job_id"],
            "chapter_number": row["chapter_number"],
            "stage": row["stage"],
            "provider": row["provider"],
            "model": row["model"],
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "cache_creation_input_tokens": int(row["cache_creation_input_tokens"] or 0),
            "cache_read_input_tokens": int(row["cache_read_input_tokens"] or 0),
            "latency_ms": int(row["latency_ms"] or 0),
            "cost_estimate_usd": float(row["cost_estimate_usd"] or 0.0),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _row_to_consistency_issue(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "project_id": row["project_id"],
            "job_id": row["job_id"],
            "chapter_number": row["chapter_number"],
            "issue_type": row["issue_type"],
            "severity": row["severity"],
            "description": row["description"],
            "location": row["location"] or "",
            "fix_instruction": row["fix_instruction"] or "",
            "status": row["status"],
            "phase": row["phase"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> Dict[str, Any]:
        raw_tags = row["tags_json"] if "tags_json" in row.keys() else "[]"
        tags = StateStore._normalize_snapshot_tags(raw_tags)
        is_favorite = bool(row["is_favorite"]) if "is_favorite" in row.keys() else False
        return {
            "id": int(row["id"]),
            "project_id": row["project_id"],
            "chapter_number": int(row["chapter_number"]),
            "chapter_title": row["chapter_title"] or "",
            "source_type": row["source_type"] or "manual",
            "note": row["note"] or "",
            "tags": tags,
            "is_favorite": is_favorite,
            "chapter_file_path": row["chapter_file_path"],
            "snapshot_path": row["snapshot_path"],
            "created_at": row["created_at"],
        }

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM projects
                ORDER BY is_active DESC, updated_at DESC
                """
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def get_active_project(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE is_active = 1 LIMIT 1"
            ).fetchone()
        return self._row_to_project(row) if row else None

    def create_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE projects SET is_active = 0")
                conn.execute(
                    """
                    INSERT INTO projects (
                        id, name, slug, workspace_dir, config_path,
                        is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project["id"],
                        project["name"],
                        project["slug"],
                        project["workspace_dir"],
                        project["config_path"],
                        1 if project.get("is_active", True) else 0,
                        project["created_at"],
                        project["updated_at"],
                    ),
                )
            return self.get_project(project["id"]) or project

    def activate_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE projects SET is_active = 0")
                conn.execute(
                    """
                    UPDATE projects
                    SET is_active = 1, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (project_id,),
                )
        return self.get_project(project_id)

    def touch_project(self, project_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET updated_at = datetime('now') WHERE id = ?",
                (project_id,),
            )

    def create_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, project_id, job_type, status, payload_json,
                    current_stage, current_chapter, result_json, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["id"],
                    job["project_id"],
                    job["job_type"],
                    job["status"],
                    json.dumps(job.get("payload", {}), ensure_ascii=False),
                    job.get("current_stage"),
                    job.get("current_chapter"),
                    json.dumps(job.get("result"), ensure_ascii=False)
                    if job.get("result") is not None
                    else None,
                    job.get("error"),
                    job["created_at"],
                    job["updated_at"],
                ),
            )
        return self.get_job(job["id"]) or job

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(
        self,
        project_id: Optional[str] = None,
        limit: int = 100,
        statuses: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        where = []
        args: List[Any] = []
        if project_id:
            where.append("project_id = ?")
            args.append(project_id)
        if statuses:
            status_values = list(statuses)
            if status_values:
                marks = ",".join("?" for _ in status_values)
                where.append(f"status IN ({marks})")
                args.extend(status_values)

        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        current_stage: Optional[str] = None,
        current_chapter: Optional[int] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        updates = ["updated_at = datetime('now')"]
        args: List[Any] = []

        if status is not None:
            updates.append("status = ?")
            args.append(status)
        if current_stage is not None:
            updates.append("current_stage = ?")
            args.append(current_stage)
        if current_chapter is not None:
            updates.append("current_chapter = ?")
            args.append(current_chapter)
        if result is not None:
            updates.append("result_json = ?")
            args.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            updates.append("error = ?")
            args.append(error)

        if len(updates) == 1:
            return self.get_job(job_id)

        args.append(job_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                tuple(args),
            )
        return self.get_job(job_id)

    def add_usage_event(self, event: Dict[str, Any]) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO usage_events (
                    project_id, job_id, chapter_number, stage, provider, model,
                    input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens,
                    latency_ms, cost_estimate_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
                """,
                (
                    event.get("project_id"),
                    event.get("job_id"),
                    event.get("chapter_number"),
                    event.get("stage"),
                    event.get("provider", "unknown"),
                    event.get("model", "unknown"),
                    int(event.get("input_tokens") or 0),
                    int(event.get("output_tokens") or 0),
                    int(event.get("cache_creation_input_tokens") or 0),
                    int(event.get("cache_read_input_tokens") or 0),
                    int(event.get("latency_ms") or 0),
                    float(event.get("cost_estimate_usd") or 0.0),
                    event.get("created_at"),
                ),
            )
            return int(cur.lastrowid)

    def list_usage_events(
        self,
        project_id: str,
        *,
        limit: int = 100,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        if days <= 0:
            days = 1
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM usage_events
                WHERE project_id = ?
                  AND created_at >= datetime('now', ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project_id, f"-{int(days)} days", int(limit)),
            ).fetchall()
        return [self._row_to_usage_event(r) for r in rows]

    def get_cost_summary(self, project_id: str, *, days: int = 30) -> Dict[str, Any]:
        if days <= 0:
            days = 1
        with self._connect() as conn:
            total = conn.execute(
                """
                SELECT
                  COUNT(*) AS calls,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
                  COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_input_tokens,
                  COALESCE(SUM(cost_estimate_usd), 0) AS cost_estimate_usd
                FROM usage_events
                WHERE project_id = ?
                  AND created_at >= datetime('now', ?)
                """,
                (project_id, f"-{int(days)} days"),
            ).fetchone()

            rows = conn.execute(
                """
                SELECT
                  model,
                  COUNT(*) AS calls,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(cost_estimate_usd), 0) AS cost_estimate_usd
                FROM usage_events
                WHERE project_id = ?
                  AND created_at >= datetime('now', ?)
                GROUP BY model
                ORDER BY cost_estimate_usd DESC
                """,
                (project_id, f"-{int(days)} days"),
            ).fetchall()

        by_model = [
            {
                "model": r["model"],
                "calls": int(r["calls"] or 0),
                "input_tokens": int(r["input_tokens"] or 0),
                "output_tokens": int(r["output_tokens"] or 0),
                "cost_estimate_usd": float(r["cost_estimate_usd"] or 0.0),
            }
            for r in rows
        ]
        return {
            "project_id": project_id,
            "period_days": int(days),
            "calls": int(total["calls"] or 0),
            "input_tokens": int(total["input_tokens"] or 0),
            "output_tokens": int(total["output_tokens"] or 0),
            "cache_creation_input_tokens": int(total["cache_creation_input_tokens"] or 0),
            "cache_read_input_tokens": int(total["cache_read_input_tokens"] or 0),
            "cost_estimate_usd": float(total["cost_estimate_usd"] or 0.0),
            "by_model": by_model,
        }

    def add_consistency_issue(self, issue: Dict[str, Any]) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO consistency_issues (
                    project_id, job_id, chapter_number, issue_type, severity,
                    description, location, fix_instruction, status, phase,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), datetime('now'))
                """,
                (
                    issue.get("project_id"),
                    issue.get("job_id"),
                    issue.get("chapter_number"),
                    issue.get("issue_type", "unknown"),
                    issue.get("severity", "warning"),
                    issue.get("description", ""),
                    issue.get("location", ""),
                    issue.get("fix_instruction", ""),
                    issue.get("status", "open"),
                    issue.get("phase", "final"),
                    issue.get("created_at"),
                ),
            )
            return int(cur.lastrowid)

    def upsert_consistency_issue(self, issue: Dict[str, Any]) -> int:
        """Insert or reopen deduplicated consistency issue."""
        project_id = issue.get("project_id")
        chapter_number = issue.get("chapter_number")
        issue_type = issue.get("issue_type", "unknown")
        severity = issue.get("severity", "warning")
        description = issue.get("description", "")
        location = issue.get("location", "")
        phase = issue.get("phase", "final")
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM consistency_issues
                WHERE project_id = ?
                  AND chapter_number IS ?
                  AND issue_type = ?
                  AND severity = ?
                  AND description = ?
                  AND location = ?
                  AND phase = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    project_id,
                    chapter_number,
                    issue_type,
                    severity,
                    description,
                    location,
                    phase,
                ),
            ).fetchone()
            if existing:
                issue_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE consistency_issues
                    SET
                        job_id = ?,
                        fix_instruction = ?,
                        status = 'open',
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (
                        issue.get("job_id"),
                        issue.get("fix_instruction", ""),
                        issue_id,
                    ),
                )
                return issue_id
        return self.add_consistency_issue(issue)

    def get_consistency_issue(
        self,
        project_id: str,
        issue_id: int,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM consistency_issues
                WHERE project_id = ? AND id = ?
                LIMIT 1
                """,
                (project_id, int(issue_id)),
            ).fetchone()
        return self._row_to_consistency_issue(row) if row else None

    def list_consistency_issues(
        self,
        project_id: str,
        *,
        limit: int = 120,
        days: int = 90,
        statuses: Optional[Iterable[str]] = None,
        severities: Optional[Iterable[str]] = None,
        chapter_number: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if days <= 0:
            days = 1

        where = [
            "project_id = ?",
            "created_at >= datetime('now', ?)",
        ]
        args: List[Any] = [project_id, f"-{int(days)} days"]

        if chapter_number is not None:
            where.append("chapter_number = ?")
            args.append(int(chapter_number))

        if statuses:
            status_values = [str(s) for s in statuses if str(s).strip()]
            if status_values:
                marks = ",".join("?" for _ in status_values)
                where.append(f"status IN ({marks})")
                args.extend(status_values)

        if severities:
            severity_values = [str(s) for s in severities if str(s).strip()]
            if severity_values:
                marks = ",".join("?" for _ in severity_values)
                where.append(f"severity IN ({marks})")
                args.extend(severity_values)

        args.append(int(limit))
        sql = f"""
            SELECT *
            FROM consistency_issues
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_consistency_issue(r) for r in rows]

    def update_consistency_issue_status(
        self,
        project_id: str,
        issue_id: int,
        status: str,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE consistency_issues
                SET status = ?, updated_at = datetime('now')
                WHERE project_id = ? AND id = ?
                """,
                (status, project_id, int(issue_id)),
            )
        return self.get_consistency_issue(project_id, issue_id)

    def resolve_open_consistency_issues_for_chapter(
        self,
        project_id: str,
        chapter_number: int,
    ) -> int:
        """Mark all open consistency issues in one chapter as resolved."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE consistency_issues
                SET status = 'resolved', updated_at = datetime('now')
                WHERE project_id = ?
                  AND chapter_number = ?
                  AND status = 'open'
                """,
                (project_id, int(chapter_number)),
            )
            return int(cur.rowcount or 0)

    def get_consistency_summary(
        self,
        project_id: str,
        *,
        days: int = 90,
    ) -> Dict[str, Any]:
        if days <= 0:
            days = 1
        with self._connect() as conn:
            total = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open_count,
                    COALESCE(SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END), 0) AS resolved_count,
                    COALESCE(SUM(CASE WHEN status = 'ignored' THEN 1 ELSE 0 END), 0) AS ignored_count,
                    COALESCE(SUM(CASE WHEN severity = 'error' THEN 1 ELSE 0 END), 0) AS error_count,
                    COALESCE(SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END), 0) AS warning_count
                FROM consistency_issues
                WHERE project_id = ?
                  AND created_at >= datetime('now', ?)
                """,
                (project_id, f"-{int(days)} days"),
            ).fetchone()

            by_type_rows = conn.execute(
                """
                SELECT issue_type, COUNT(*) AS count
                FROM consistency_issues
                WHERE project_id = ?
                  AND created_at >= datetime('now', ?)
                GROUP BY issue_type
                ORDER BY count DESC
                """,
                (project_id, f"-{int(days)} days"),
            ).fetchall()

        return {
            "project_id": project_id,
            "period_days": int(days),
            "total": int(total["total"] or 0),
            "open_count": int(total["open_count"] or 0),
            "resolved_count": int(total["resolved_count"] or 0),
            "ignored_count": int(total["ignored_count"] or 0),
            "error_count": int(total["error_count"] or 0),
            "warning_count": int(total["warning_count"] or 0),
            "by_type": [
                {"issue_type": row["issue_type"], "count": int(row["count"] or 0)}
                for row in by_type_rows
            ],
        }

    def add_chapter_snapshot(self, snapshot: Dict[str, Any]) -> int:
        tags = self._normalize_snapshot_tags(snapshot.get("tags"))
        is_favorite = bool(snapshot.get("is_favorite", False))
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO chapter_snapshots (
                    project_id, chapter_number, chapter_title, source_type, note,
                    tags_json, is_favorite, chapter_file_path, snapshot_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
                """,
                (
                    snapshot.get("project_id"),
                    int(snapshot.get("chapter_number") or 0),
                    snapshot.get("chapter_title", ""),
                    snapshot.get("source_type", "manual"),
                    snapshot.get("note", ""),
                    json.dumps(tags, ensure_ascii=False),
                    1 if is_favorite else 0,
                    snapshot.get("chapter_file_path", ""),
                    snapshot.get("snapshot_path", ""),
                    snapshot.get("created_at"),
                ),
            )
            return int(cur.lastrowid)

    def get_chapter_snapshot(self, project_id: str, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM chapter_snapshots
                WHERE project_id = ? AND id = ?
                LIMIT 1
                """,
                (project_id, int(snapshot_id)),
            ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def list_chapter_snapshots(
        self,
        project_id: str,
        *,
        chapter_number: Optional[int] = None,
        query: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        favorites_only: bool = False,
        limit: int = 120,
    ) -> List[Dict[str, Any]]:
        where = ["project_id = ?"]
        args: List[Any] = [project_id]
        if chapter_number is not None:
            where.append("chapter_number = ?")
            args.append(int(chapter_number))
        if favorites_only:
            where.append("is_favorite = 1")
        search_text = str(query or "").strip()
        if search_text:
            pattern = f"%{search_text}%"
            where.append(
                "(chapter_title LIKE ? OR note LIKE ? OR snapshot_path LIKE ? OR tags_json LIKE ?)"
            )
            args.extend([pattern, pattern, pattern, pattern])
        if tags:
            normalized_tags = self._normalize_snapshot_tags(list(tags))
            for tag in normalized_tags:
                where.append("tags_json LIKE ?")
                args.append(f'%"{tag}"%')
        args.append(int(limit))
        sql = f"""
            SELECT *
            FROM chapter_snapshots
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def update_chapter_snapshot(
        self,
        project_id: str,
        snapshot_id: int,
        *,
        note: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        is_favorite: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        updates: List[str] = []
        args: List[Any] = []
        if note is not None:
            updates.append("note = ?")
            args.append(str(note))
        if tags is not None:
            normalized_tags = self._normalize_snapshot_tags(list(tags))
            updates.append("tags_json = ?")
            args.append(json.dumps(normalized_tags, ensure_ascii=False))
        if is_favorite is not None:
            updates.append("is_favorite = ?")
            args.append(1 if bool(is_favorite) else 0)
        if not updates:
            return self.get_chapter_snapshot(project_id, snapshot_id)

        args.extend([project_id, int(snapshot_id)])
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE chapter_snapshots
                SET {", ".join(updates)}
                WHERE project_id = ? AND id = ?
                """,
                tuple(args),
            )
        return self.get_chapter_snapshot(project_id, snapshot_id)
