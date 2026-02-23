"""Chapter and setting document indexing logic."""
import os
import json
import logging
import glob

logger = logging.getLogger(__name__)

PENDING_FILE = "pending_index.json"


def index_chapter(rag_manager, chapter_number: int, chapter_text: str, novel_dir: str):
    """Index a chapter's full text into LightRAG. Track pending on failure."""
    try:
        header = f"[第{chapter_number}章]\n"
        rag_manager.index_text(header + chapter_text)
        _remove_pending(novel_dir, chapter_number)
    except Exception:
        _mark_pending(novel_dir, chapter_number)
        raise


def index_setting_docs(rag_manager, config: dict):
    """Index setting documents into LightRAG (one-time initialization)."""
    novel_cfg = config.get("novel", {})
    docs = novel_cfg.get("setting_docs", [])
    if not docs:
        # Fallback to legacy single-file keys
        for key in ("setting_file", "style_guide_file"):
            path = novel_cfg.get(key, "")
            if path and path not in docs:
                docs.append(path)
    for path in docs:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            logger.info(f"Indexing setting doc: {path} ({len(text)} chars)")
            rag_manager.index_text(text)


def retry_pending(rag_manager, novel_dir: str):
    """Retry indexing chapters that previously failed."""
    pending = _load_pending(novel_dir)
    if not pending:
        return
    chapters_dir = os.path.join(novel_dir, "chapters")
    for ch_num in list(pending):
        files = glob.glob(os.path.join(chapters_dir, f"第{ch_num}章*.md"))
        if not files:
            continue
        with open(files[0], "r", encoding="utf-8") as f:
            text = f.read()
        try:
            header = f"[第{ch_num}章]\n"
            rag_manager.index_text(header + text)
            _remove_pending(novel_dir, ch_num)
            logger.info(f"Retry indexed chapter {ch_num}")
        except Exception as e:
            logger.warning(f"Retry failed for chapter {ch_num}: {e}")


def _pending_path(novel_dir: str) -> str:
    return os.path.join(novel_dir, ".pending", PENDING_FILE)


def _load_pending(novel_dir: str) -> list:
    path = _pending_path(novel_dir)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def _mark_pending(novel_dir: str, chapter_number: int):
    pending = _load_pending(novel_dir)
    if chapter_number not in pending:
        pending.append(chapter_number)
    path = _pending_path(novel_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(pending, f)


def _remove_pending(novel_dir: str, chapter_number: int):
    pending = _load_pending(novel_dir)
    if chapter_number in pending:
        pending.remove(chapter_number)
        with open(_pending_path(novel_dir), "w") as f:
            json.dump(pending, f)
