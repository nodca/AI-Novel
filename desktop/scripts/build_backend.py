"""Build bundled backend executable for desktop release."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


LEAN_EXCLUDE_MODULES: tuple[str, ...] = (
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "tensorflow",
    "onnxruntime",
    "cv2",
    "sklearn",
    "transformers",
    "sentence_transformers",
    "matplotlib",
    "PIL",
    "nltk",
    "tkinter",
    "pandas",
    "scipy",
    "sympy",
    "numba",
    "pyarrow",
)


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    values = []
    seen = set()
    for item in raw.split(","):
        value = item.strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def build_backend(
    *,
    dry_run: bool = False,
    lean: bool = True,
    extra_excludes: list[str] | None = None,
) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    desktop_dir = repo_root / "desktop"
    entry = desktop_dir / "backend" / "run_backend.py"
    dist_dir = desktop_dir / ".backend-dist"
    work_dir = desktop_dir / ".backend-build"
    spec_dir = desktop_dir / ".backend-spec"

    if not entry.exists():
        raise FileNotFoundError(f"Backend entry script not found: {entry}")

    for folder in (dist_dir, work_dir, spec_dir):
        if folder.exists():
            shutil.rmtree(folder)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "ai-novel-backend",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(repo_root),
    ]
    excludes: list[str] = []
    if lean:
        excludes.extend(LEAN_EXCLUDE_MODULES)
    excludes.extend(extra_excludes or [])
    excludes = _dedupe(excludes)
    for module in excludes:
        cmd.extend(["--exclude-module", module])
    cmd.append(str(entry))

    print("building backend executable...")
    if excludes:
        print(f"[build_backend] excluded modules ({len(excludes)}): {', '.join(excludes)}")
    print(" ".join(cmd))
    if not dry_run:
        subprocess.check_call(cmd, cwd=str(repo_root))

    exe = dist_dir / "ai-novel-backend.exe"
    if not dry_run and not exe.exists():
        raise RuntimeError(f"Build succeeded but executable not found: {exe}")
    return exe


def main() -> int:
    parser = argparse.ArgumentParser(description="Build desktop backend executable")
    parser.add_argument("--dry-run", action="store_true", help="Print build command without executing it")
    parser.add_argument(
        "--lean",
        action=argparse.BooleanOptionalAction,
        default=_env_enabled("AI_NOVEL_BACKEND_LEAN", True),
        help="Exclude heavy optional ML modules from PyInstaller output",
    )
    parser.add_argument(
        "--exclude-module",
        action="append",
        default=[],
        help="Extra module to exclude (repeatable)",
    )
    args = parser.parse_args()

    env_excludes = _parse_csv(os.getenv("AI_NOVEL_BACKEND_EXCLUDE_MODULES"))
    cli_excludes = [item.strip() for item in (args.exclude_module or []) if item and item.strip()]
    extra_excludes = _dedupe(env_excludes + cli_excludes)

    try:
        exe = build_backend(dry_run=args.dry_run, lean=bool(args.lean), extra_excludes=extra_excludes)
    except Exception as exc:  # pragma: no cover
        print(f"[build_backend] failed: {exc}", file=sys.stderr)
        return 1

    suffix = " (dry-run)" if args.dry_run else ""
    print(f"[build_backend] output: {exe}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
