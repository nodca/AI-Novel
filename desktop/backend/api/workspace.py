"""Workspace management for per-novel project isolation."""

from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from desktop.backend.api.config import AppPaths
from desktop.backend.api.state_store import StateStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(name: str) -> str:
    raw = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if slug:
        return slug[:40]
    return f"novel-{uuid.uuid4().hex[:8]}"


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class WorkspaceService:
    """Creates and updates isolated per-project workspaces."""

    def __init__(self, paths: AppPaths, state: StateStore):
        self.paths = paths
        self.state = state

    def create_project(self, name: str) -> Dict[str, Any]:
        slug = _slugify(name)
        workspace_dir = self.paths.projects_root / slug
        while workspace_dir.exists():
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"
            workspace_dir = self.paths.projects_root / slug

        self._bootstrap_workspace(workspace_dir)
        config_path = workspace_dir / "config.yaml"
        config = self._build_initial_config(workspace_dir)
        self._write_yaml(config_path, config)

        now = _utc_now_iso()
        project = self.state.create_project(
            {
                "id": uuid.uuid4().hex,
                "name": name.strip(),
                "slug": slug,
                "workspace_dir": str(workspace_dir),
                "config_path": str(config_path),
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        return project

    def activate(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.state.activate_project(project_id)

    def get_config(self, project_id: str) -> Dict[str, Any]:
        project = self.state.get_project(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")
        return self._read_yaml(Path(project["config_path"]))

    def patch_config(self, project_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        project = self.state.get_project(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

        config_path = Path(project["config_path"])
        config = self._read_yaml(config_path)
        merged = _deep_merge(config, patch)
        self._write_yaml(config_path, merged)
        self.state.touch_project(project_id)
        return merged

    def import_existing_content(
        self,
        project_id: str,
        *,
        source_root: str,
        overwrite: bool = True,
        import_database: bool = True,
        import_lightrag: bool = True,
    ) -> Dict[str, Any]:
        project = self.state.get_project(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

        source_dir = Path(source_root).expanduser().resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

        workspace_dir = Path(project["workspace_dir"]).resolve()
        config_path = Path(project["config_path"]).resolve()
        imported: Dict[str, str] = {}
        warnings: list[str] = []

        chapters_src = source_dir / "chapters"
        if not chapters_src.exists():
            raise FileNotFoundError(
                f"No 'chapters' directory under source root: {source_dir}"
            )
        self._copy_dir(chapters_src, workspace_dir / "chapters", overwrite=overwrite)
        imported["chapters"] = str(chapters_src)

        outlines_src = self._first_existing_dir(
            [source_dir / "outlines", source_dir / "章节细纲"]
        )
        if outlines_src:
            self._copy_dir(outlines_src, workspace_dir / "outlines", overwrite=overwrite)
            imported["outlines"] = str(outlines_src)
        else:
            warnings.append("未找到 outlines 或 章节细纲 目录，已跳过细纲导入")

        docs_plans_src = source_dir / "docs" / "plans"
        if docs_plans_src.exists():
            self._copy_dir(
                docs_plans_src, workspace_dir / "docs" / "plans", overwrite=overwrite
            )
            imported["docs_plans"] = str(docs_plans_src)
        else:
            warnings.append("未找到 docs/plans，已跳过设定文档导入")

        docs_style_src = source_dir / "docs" / "style"
        if docs_style_src.exists():
            self._copy_dir(
                docs_style_src, workspace_dir / "docs" / "style", overwrite=overwrite
            )
            imported["docs_style"] = str(docs_style_src)
        else:
            warnings.append("未找到 docs/style，已跳过风格文档导入")

        if import_database:
            db_src = source_dir / "novel_state.db"
            if db_src.exists() and db_src.is_file():
                shutil.copy2(db_src, workspace_dir / "novel_state.db")
                imported["database"] = str(db_src)
            else:
                warnings.append("未找到 novel_state.db，已跳过数据库导入")

        if import_lightrag:
            lightrag_src = source_dir / "lightrag_data"
            if lightrag_src.exists() and lightrag_src.is_dir():
                self._copy_dir(
                    lightrag_src, workspace_dir / "lightrag_data", overwrite=overwrite
                )
                imported["lightrag_data"] = str(lightrag_src)
            else:
                warnings.append("未找到 lightrag_data，已跳过 LightRAG 数据导入")

        self._sync_config_after_import(config_path, workspace_dir)
        self.state.touch_project(project_id)

        chapter_files = len(
            [p for p in (workspace_dir / "chapters").glob("*.md") if p.is_file()]
        )
        return {
            "project_id": project_id,
            "workspace_dir": str(workspace_dir),
            "imported": imported,
            "warnings": warnings,
            "chapter_files": chapter_files,
        }

    def find_chapter_file(self, project_id: str, chapter_number: int) -> Optional[Path]:
        project = self.state.get_project(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")
        chapter_prefix = f"第{int(chapter_number)}章"
        chapters_dir = Path(project["workspace_dir"]) / "chapters"
        if not chapters_dir.exists():
            return None
        matches = sorted(chapters_dir.glob(f"{chapter_prefix}*.md"))
        if matches:
            return matches[0]
        fallback = chapters_dir / f"{chapter_prefix}.md"
        return fallback if fallback.exists() else None

    def create_snapshot(
        self,
        project_id: str,
        chapter_number: int,
        *,
        source_type: str = "manual",
        note: str = "",
        tags: Optional[list[str]] = None,
        is_favorite: bool = False,
    ) -> Dict[str, Any]:
        project = self.state.get_project(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")
        chapter_file = self.find_chapter_file(project_id, chapter_number)
        if not chapter_file:
            raise FileNotFoundError(f"Chapter file for chapter {chapter_number} not found")

        chapter_title = ""
        try:
            first_line = chapter_file.read_text(encoding="utf-8").splitlines()[0]
            chapter_title = first_line.lstrip("#").strip()
        except Exception:
            chapter_title = f"第{chapter_number}章"

        snapshots_dir = Path(project["workspace_dir"]) / ".snapshots" / f"chapter_{int(chapter_number)}"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        snapshot_file = snapshots_dir / f"{stamp}-{uuid.uuid4().hex[:6]}.md"
        shutil.copy2(chapter_file, snapshot_file)

        snapshot_id = self.state.add_chapter_snapshot(
            {
                "project_id": project_id,
                "chapter_number": int(chapter_number),
                "chapter_title": chapter_title,
                "source_type": source_type,
                "note": note,
                "tags": tags or [],
                "is_favorite": bool(is_favorite),
                "chapter_file_path": str(chapter_file),
                "snapshot_path": str(snapshot_file),
            }
        )
        self.state.touch_project(project_id)
        created = self.state.get_chapter_snapshot(project_id, snapshot_id)
        if not created:
            raise RuntimeError("Snapshot created but not found")
        return created

    def restore_snapshot(self, project_id: str, snapshot_id: int) -> Dict[str, Any]:
        project = self.state.get_project(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")
        snapshot = self.state.get_chapter_snapshot(project_id, snapshot_id)
        if not snapshot:
            raise FileNotFoundError(f"Snapshot {snapshot_id} not found")

        source_path = Path(snapshot["snapshot_path"])
        if not source_path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {source_path}")

        chapter_number = int(snapshot["chapter_number"])
        target_path = self.find_chapter_file(project_id, chapter_number)
        if not target_path:
            target_path = Path(snapshot["chapter_file_path"])
        target_path.parent.mkdir(parents=True, exist_ok=True)

        backup_snapshot = None
        if target_path.exists():
            backup_snapshot = self.create_snapshot(
                project_id,
                chapter_number,
                source_type="restore_backup",
                note=f"Restore backup before snapshot #{snapshot_id}",
            )

        shutil.copy2(source_path, target_path)
        self.state.touch_project(project_id)
        return {
            "snapshot": snapshot,
            "restored_chapter_file": str(target_path),
            "backup_snapshot": backup_snapshot,
        }

    def _bootstrap_workspace(self, workspace_dir: Path) -> None:
        (workspace_dir / "chapters").mkdir(parents=True, exist_ok=True)
        (workspace_dir / "outlines").mkdir(parents=True, exist_ok=True)
        (workspace_dir / ".cache").mkdir(parents=True, exist_ok=True)
        (workspace_dir / ".pending").mkdir(parents=True, exist_ok=True)
        (workspace_dir / "lightrag_data").mkdir(parents=True, exist_ok=True)
        (workspace_dir / "docs" / "plans").mkdir(parents=True, exist_ok=True)
        (workspace_dir / "docs" / "style").mkdir(parents=True, exist_ok=True)

        setting_file = workspace_dir / "docs" / "plans" / "setting.md"
        style_file = workspace_dir / "docs" / "style" / "style-guide.md"
        if not setting_file.exists():
            setting_file.write_text(
                "# 设定文档\n\n请在这里维护本书世界观设定。\n",
                encoding="utf-8",
            )
        if not style_file.exists():
            style_file.write_text(
                "# 写作风格指南\n\n请在这里维护本书写作风格与禁忌词。\n",
                encoding="utf-8",
            )

    def _build_initial_config(self, workspace_dir: Path) -> Dict[str, Any]:
        setting_path = workspace_dir / "docs" / "plans" / "setting.md"
        style_path = workspace_dir / "docs" / "style" / "style-guide.md"

        base = self._load_seed_config()
        merged = _deep_merge(
            base,
            {
                "novel": {
                    "novel_dir": str(workspace_dir),
                    "outline_dir": str(workspace_dir / "outlines"),
                    "setting_file": str(setting_path),
                    "style_guide_file": str(style_path),
                    "setting_docs": [str(setting_path), str(style_path)],
                },
                "database": {
                    "url": f"sqlite:///{(workspace_dir / 'novel_state.db').as_posix()}",
                },
                "lightrag": {
                    "working_dir": str(workspace_dir / "lightrag_data"),
                },
            },
        )
        return merged

    @staticmethod
    def _read_yaml(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data

    @staticmethod
    def _write_yaml(path: Path, payload: Dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

    @staticmethod
    def _first_existing_dir(candidates: list[Path]) -> Optional[Path]:
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def _copy_dir(src: Path, dst: Path, *, overwrite: bool) -> None:
        if dst.exists():
            if not overwrite:
                raise FileExistsError(f"Target already exists: {dst}")
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    def _sync_config_after_import(self, config_path: Path, workspace_dir: Path) -> None:
        config = self._read_yaml(config_path)
        novel_cfg = config.get("novel", {})
        if not isinstance(novel_cfg, dict):
            novel_cfg = {}

        novel_cfg["novel_dir"] = str(workspace_dir)
        novel_cfg["outline_dir"] = str(workspace_dir / "outlines")

        plans_dir = workspace_dir / "docs" / "plans"
        style_dir = workspace_dir / "docs" / "style"
        plan_docs = sorted(p for p in plans_dir.glob("*.md") if p.is_file())
        style_docs = sorted(p for p in style_dir.glob("*.md") if p.is_file())

        if plan_docs:
            preferred_setting = next(
                (p for p in plan_docs if "设定" in p.name),
                plan_docs[0],
            )
            novel_cfg["setting_file"] = str(preferred_setting)

        if style_docs:
            preferred_style = next(
                (p for p in style_docs if "风格" in p.name),
                style_docs[0],
            )
            novel_cfg["style_guide_file"] = str(preferred_style)

        setting_docs = [str(p) for p in [*plan_docs, *style_docs]]
        if setting_docs:
            novel_cfg["setting_docs"] = setting_docs

        config["novel"] = novel_cfg
        self._write_yaml(config_path, config)

    @staticmethod
    def _load_seed_config() -> Dict[str, Any]:
        root_cfg = Path("config.yaml")
        if root_cfg.exists():
            with root_cfg.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                return data
        return {
            "anthropic": {
                "api_key": "",
                "base_url": "https://api.anthropic.com",
                "writing_model": "claude-opus-4-6-20260205",
                "analysis_model": "claude-sonnet-4-6-20260219",
                "writing_temperature": 0.8,
                "analysis_temperature": 0.3,
                "max_retries": 3,
                "timeout": 600,
            },
            "lightrag": {
                "llm": {"model": "qwen3.5-plus", "api_key": "", "base_url": "", "timeout": 180, "max_tokens": 4096},
                "embedding": {"model": "BAAI/bge-m3", "api_key": "", "base_url": "", "dim": 1024, "max_tokens": 8192},
                "rerank": {"model": "BAAI/bge-reranker-v2-m3", "api_key": "", "base_url": ""},
            },
            "generation": {
                "max_input_tokens_per_scene": 12000,
                "summary_arc_interval": 10,
                "voice_samples_limit": 4,
            },
        }
