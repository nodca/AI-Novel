"""Main pipeline - orchestrates all stages (0→1→2→2.5→3)."""
import os
import json
import hashlib
import logging
import time

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _load_style_guide(config: dict) -> str:
    path = config.get("novel", {}).get("style_guide_file", "")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _emit_consistency_report(config: dict, chapter_number: int, report, phase: str) -> None:
    telemetry = config.get("_telemetry", {})
    callback = telemetry.get("consistency_callback") if isinstance(telemetry, dict) else None
    if not callable(callback):
        return
    payload = {
        "phase": phase,
        "chapter_number": chapter_number,
        "passed": bool(getattr(report, "passed", False)),
        "issues": [
            {
                "type": getattr(issue, "type", "unknown"),
                "severity": getattr(issue, "severity", "warning"),
                "description": getattr(issue, "description", ""),
                "location": getattr(issue, "location", ""),
                "fix_instruction": getattr(issue, "fix_instruction", ""),
            }
            for issue in getattr(report, "issues", [])
        ],
    }
    try:
        callback(payload)
    except Exception as exc:  # pragma: no cover
        logger.warning("consistency callback failed: %s", exc)


def _check_control(should_cancel=None, should_pause=None) -> None:
    from core.interrupts import GenerationCancelled

    while callable(should_pause) and should_pause():
        if callable(should_cancel) and should_cancel():
            raise GenerationCancelled("Job canceled by user")
        time.sleep(0.4)
    if callable(should_cancel) and should_cancel():
        raise GenerationCancelled("Job canceled by user")


def init_project(config: dict, progress_callback=None):
    """Initialize project: create DB, index setting docs, generate world summary."""
    from db.database import get_engine, init_db, get_session
    from llm.claude_client import ClaudeClient
    from rag.lightrag_manager import LightRAGManager
    from rag.indexer import index_setting_docs, retry_pending
    from db.models import Summary

    engine = get_engine(config)
    init_db(engine)
    session = get_session(engine)
    llm = ClaudeClient(config)
    rag = LightRAGManager(config)

    # Index setting documents
    if progress_callback:
        progress_callback("stage:init:index_settings", None)
    logger.info("Indexing setting documents...")
    index_setting_docs(rag, config)

    # Retry any pending chapter indexes
    novel_dir = config.get("novel", {}).get("novel_dir", "")
    if novel_dir:
        if progress_callback:
            progress_callback("stage:init:retry_pending", None)
        retry_pending(rag, novel_dir)

    # Generate world summary if not exists
    existing = session.query(Summary).filter_by(level="world").first()
    if not existing:
        setting_file = config.get("novel", {}).get("setting_file", "")
        if setting_file and os.path.exists(setting_file):
            with open(setting_file, "r", encoding="utf-8") as f:
                setting_text = f.read()
            logger.info("Generating world summary...")
            if progress_callback:
                progress_callback("stage:init:world_summary", None)
            prompt = f"""请从以下设定文档中提炼一份300-500字的世界观精简摘要。
包含：魔法体系基本规则、等级划分概要、世界基本设定。
不要包含具体角色信息或剧情细节。

设定文档：
{setting_text}

直接输出摘要："""
            summary = llm.call_sonnet(prompt, max_tokens=1024)
            session.add(Summary(level="world", content=summary))
            session.commit()
            logger.info("World summary generated and saved")
    else:
        logger.info("World summary already exists, skipping")

    session.close()
    logger.info("Project initialization complete")


def reprocess_chapter(config: dict, chapter_number: int, progress_callback=None):
    """Re-extract state and re-index a chapter after manual edits."""
    import glob
    from db.database import get_engine, init_db, get_session
    from llm.claude_client import ClaudeClient
    from rag.lightrag_manager import LightRAGManager
    from rag.indexer import index_chapter
    from core.postprocess import _extract_data, _validate_extract_data, _write_db, _save_pending_extract

    engine = get_engine(config)
    init_db(engine)
    session = get_session(engine)
    llm = ClaudeClient(config)
    rag = LightRAGManager(config)
    novel_dir = config.get("novel", {}).get("novel_dir", "")
    gen_cfg = config.get("generation", {})
    voice_limit = int(gen_cfg.get("voice_samples_limit", 10))
    arc_interval = int(gen_cfg.get("summary_arc_interval", 10))

    # Find chapter file
    chapters_dir = os.path.join(novel_dir, "chapters")
    files = glob.glob(os.path.join(chapters_dir, f"第{chapter_number}章*.md"))
    if not files:
        logger.error(f"Chapter {chapter_number} file not found in {chapters_dir}")
        return
    with open(files[0], "r", encoding="utf-8") as f:
        chapter_text = f.read()
    # Strip markdown title line
    lines = chapter_text.split("\n", 2)
    if lines and lines[0].startswith("# "):
        chapter_text = lines[2] if len(lines) > 2 else ""

    logger.info(f"Reprocessing chapter {chapter_number} from {files[0]}")

    try:
        if progress_callback:
            progress_callback("stage:reprocess:extract", chapter_number)
        # Re-extract
        data = _extract_data(chapter_number, chapter_text, llm)
        if not data:
            logger.error("Extraction returned empty data")
            return
        errors = _validate_extract_data(data)
        if errors:
            logger.error(f"Validation failed: {errors}")
            return

        # Re-write DB
        if progress_callback:
            progress_callback("stage:reprocess:db_write", chapter_number)
        _write_db(session, chapter_number, data, voice_limit=voice_limit, arc_interval=arc_interval)
        session.commit()
        logger.info("DB updated")

        # Re-index LightRAG
        if progress_callback:
            progress_callback("stage:reprocess:rag_index", chapter_number)
        index_chapter(rag, chapter_number, chapter_text, novel_dir)
        logger.info("LightRAG re-indexed")

        logger.info(f"Reprocess chapter {chapter_number} complete")
    except Exception as e:
        session.rollback()
        logger.error(f"Reprocess failed: {e}")
        raise
    finally:
        session.close()


def run_chapter(
    config: dict,
    outline_file: str,
    chapter_number: int,
    auto_confirm: bool = False,
    progress_callback=None,
    should_cancel=None,
    should_pause=None,
) -> str:
    """Run the full pipeline for a single chapter."""
    from db.database import get_engine, init_db, get_session
    from llm.claude_client import ClaudeClient
    from rag.lightrag_manager import LightRAGManager
    from rag.indexer import retry_pending
    from core.outline_parser import parse_outline
    from core.precheck import run_precheck
    from core.writer import write_scenes, targeted_rewrite
    from core.consistency import run_consistency_check
    from core.postprocess import run_postprocess

    engine = get_engine(config)
    init_db(engine)
    session = get_session(engine)
    llm = ClaudeClient(config)
    rag = LightRAGManager(config)
    novel_dir = config.get("novel", {}).get("novel_dir", "")
    style_guide = _load_style_guide(config)

    # Retry pending LightRAG indexes
    if novel_dir:
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        retry_pending(rag, novel_dir)

    try:
        # === Stage 0: Parse outline ===
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        if progress_callback:
            progress_callback("stage:0:outline", chapter_number)
        logger.info(f"=== Chapter {chapter_number}: Stage 0 - Parse outline ===")
        chapter_info = parse_outline(outline_file, chapter_number)
        title = chapter_info.get("title", f"第{chapter_number}章")
        logger.info(f"Title: {title}, Characters: {chapter_info.get('characters', [])}")

        # === Stage 1: Precheck + Scene Planning (with cache) ===
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        if progress_callback:
            progress_callback("stage:1:precheck", chapter_number)
        logger.info(f"=== Chapter {chapter_number}: Stage 1 - Precheck + Scene Planning ===")
        cache_dir = os.path.join(novel_dir or ".", ".cache")
        outline_hash = hashlib.md5(chapter_info.get("_raw_text", "").encode()).hexdigest()[:12]
        cache_file = os.path.join(cache_dir, f"stage1_ch{chapter_number}_{outline_hash}.json")

        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                result = json.load(f)
            logger.info(f"Loaded Stage 1 cache: {cache_file}")
        else:
            result = run_precheck(chapter_info, chapter_number, session, llm, rag)
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved Stage 1 cache: {cache_file}")

        # Report contradictions
        contradictions = result.get("contradictions", [])
        if contradictions:
            logger.warning(f"Found {len(contradictions)} contradictions:")
            for c in contradictions:
                logger.warning(f"  - {c.get('description', '')}")
                logger.warning(f"    建议: {c.get('suggestion', '')}")
            has_errors = any(c.get("severity") == "error" for c in contradictions)
            if has_errors and not auto_confirm:
                resp = input("\n发现严重矛盾，是否继续生成？(y=继续 / n=中止): ").strip().lower()
                if resp != "y":
                    logger.info("User aborted due to contradictions")
                    return ""

        scene_contracts = result.get("scenes", [])
        logger.info(f"Planned {len(scene_contracts)} scenes")

        # === Stage 2: Scene-by-scene generation ===
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        if progress_callback:
            progress_callback("stage:2:write", chapter_number)
        logger.info(f"=== Chapter {chapter_number}: Stage 2 - Generating scenes ===")
        chapter_text = write_scenes(
            scene_contracts,
            session,
            llm,
            rag,
            style_guide,
            config,
            should_cancel=should_cancel,
            should_pause=should_pause,
        )

        if not chapter_text.strip():
            logger.error("Generation returned empty content")
            return ""

        # === Stage 2.5: Consistency check + targeted fix ===
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        if progress_callback:
            progress_callback("stage:2.5:consistency", chapter_number)
        logger.info(f"=== Chapter {chapter_number}: Stage 2.5 - Consistency check ===")
        report = run_consistency_check(chapter_number, chapter_text, scene_contracts, session, llm)
        _emit_consistency_report(config, chapter_number, report, phase="initial")

        if not report.passed:
            errors = [i for i in report.issues if i.severity == "error"]
            logger.warning(f"Consistency check found {len(errors)} errors, attempting fix...")
            for e in errors:
                logger.warning(f"  [error] {e.type}: {e.description}")

            # Targeted rewrite for first error
            if errors:
                fix = errors[0]
                # Build rewrite context from scene contracts
                from core.context_builder import _build_scene_contract, _build_pov_knowledge
                rewrite_ctx_parts = [_build_scene_contract(sc) for sc in scene_contracts]
                pov_chars = set(sc.get("pov_character", "") for sc in scene_contracts)
                for pov in pov_chars:
                    if pov:
                        pk = _build_pov_knowledge(session, pov)
                        if pk:
                            rewrite_ctx_parts.append(pk)
                rewrite_ctx = "\n\n".join(p for p in rewrite_ctx_parts if p)
                chapter_text = targeted_rewrite(
                    chapter_text, fix.fix_instruction, fix.location, llm,
                    scene_prompt=rewrite_ctx,
                )
                # Re-check
                report = run_consistency_check(chapter_number, chapter_text, scene_contracts, session, llm)
                if not report.passed:
                    remaining = [i for i in report.issues if i.severity == "error"]
                    logger.warning(f"Still {len(remaining)} errors after fix:")
                    for e in remaining:
                        logger.warning(f"  [error] {e.type}: {e.description}")
                    if not auto_confirm:
                        resp = input("一致性校验仍有错误，是否继续？(y=继续 / n=中止): ").strip().lower()
                        if resp != "y":
                            _emit_consistency_report(config, chapter_number, report, phase="final")
                            return ""

        _emit_consistency_report(config, chapter_number, report, phase="final")

        # Log warnings
        warnings = [i for i in report.issues if i.severity == "warning"]
        for w in warnings:
            logger.info(f"[warning] {w.type}: {w.description}")

        # === Stage 3: Postprocess ===
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        if progress_callback:
            progress_callback("stage:3:postprocess", chapter_number)
        logger.info(f"=== Chapter {chapter_number}: Stage 3 - Postprocessing ===")
        run_postprocess(chapter_number, chapter_text, title, novel_dir, session, llm, rag, config)

        logger.info(f"=== Chapter {chapter_number} complete ===")
        return chapter_text

    except Exception as e:
        session.rollback()
        logger.error(f"Pipeline failed for chapter {chapter_number}: {e}")
        raise
    finally:
        session.close()
