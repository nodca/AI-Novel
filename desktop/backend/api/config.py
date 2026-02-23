"""App-level path configuration for desktop runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_HOME_ENV = "AI_NOVEL_APP_HOME"


@dataclass(frozen=True)
class AppPaths:
    """Filesystem locations used by desktop app runtime."""

    home: Path
    projects_root: Path
    state_db: Path
    logs_dir: Path


def build_paths() -> AppPaths:
    """Resolve and create all required runtime folders."""
    env_home = os.getenv(APP_HOME_ENV, "").strip()
    if env_home:
        home = Path(env_home).expanduser().resolve()
    else:
        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            home = (Path(appdata) / "AI-Novel-V2").resolve()
        else:
            home = (Path.home() / ".ai-novel-v2").resolve()

    projects_root = home / "projects"
    logs_dir = home / "logs"
    state_db = home / "app_state.db"

    projects_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    return AppPaths(
        home=home,
        projects_root=projects_root,
        state_db=state_db,
        logs_dir=logs_dir,
    )

