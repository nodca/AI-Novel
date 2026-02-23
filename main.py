"""AI-Novel V2 CLI entry point."""
import argparse
import yaml
import sys


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_write(args):
    from core.pipeline import run_chapter
    config = load_config(args.config)
    run_chapter(config, args.outline, args.chapter, auto_confirm=args.yes)


def cmd_batch(args):
    from core.pipeline import run_chapter
    config = load_config(args.config)
    for ch in range(args.start, args.end + 1):
        print(f"\n{'='*40} Chapter {ch} {'='*40}")
        run_chapter(config, args.outline, ch, auto_confirm=args.yes)


def cmd_init(args):
    from core.pipeline import init_project
    config = load_config(args.config)
    init_project(config)


def cmd_reprocess(args):
    from core.pipeline import reprocess_chapter
    config = load_config(args.config)
    reprocess_chapter(config, args.chapter)


def cmd_reindex(args):
    import os
    import glob
    import logging
    import time
    from rag.lightrag_manager import LightRAGManager
    from rag.indexer import index_setting_docs, index_chapter

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)
    config = load_config(args.config)
    novel_dir = config.get("novel", {}).get("novel_dir", "")
    rag_dir = config.get("lightrag", {}).get("working_dir", "./lightrag_data")

    if args.clean and os.path.exists(rag_dir):
        import shutil
        shutil.rmtree(rag_dir)
        logger.info(f"Deleted {rag_dir}")

    rag = LightRAGManager(config)

    # Index setting docs
    logger.info("Indexing setting documents...")
    index_setting_docs(rag, config)

    _CN_NUM = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    def _chapter_num(basename):
        m = __import__('re').search(r'第(\d+)章', basename)
        if m:
            return int(m.group(1))
        m = __import__('re').search(r'第([一二三四五六七八九十]+)章', basename)
        if m:
            s = m.group(1)
            if len(s) == 1:
                return _CN_NUM.get(s, 0)
            if s.startswith('十'):
                return 10 + _CN_NUM.get(s[1:], 0)
            if s.endswith('十'):
                return _CN_NUM.get(s[0], 0) * 10
            if '十' in s:
                parts = s.split('十')
                return _CN_NUM.get(parts[0], 0) * 10 + _CN_NUM.get(parts[1], 0)
        return 0

    # Index chapters
    chapters_dir = os.path.join(novel_dir, "chapters")
    all_files = glob.glob(os.path.join(chapters_dir, "第*章*.md"))
    files = sorted(
        [f for f in all_files if _chapter_num(os.path.basename(f)) > 0],
        key=lambda f: _chapter_num(os.path.basename(f)))
    logger.info(f"Found {len(files)} chapter files")
    for filepath in files:
        ch_num = _chapter_num(os.path.basename(filepath))
        if not ch_num:
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        # Strip markdown title
        lines = text.split("\n", 2)
        if lines and lines[0].startswith("# "):
            text = lines[2] if len(lines) > 2 else ""
        logger.info(f"Indexing chapter {ch_num}...")
        index_chapter(rag, ch_num, text, novel_dir)
        time.sleep(3)

    logger.info("Reindex complete")


def main():
    parser = argparse.ArgumentParser(description="AI-Novel V2")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command")

    p_write = sub.add_parser("write", help="Generate a single chapter")
    p_write.add_argument("outline", help="Outline file path")
    p_write.add_argument("chapter", type=int, help="Chapter number")
    p_write.add_argument("--yes", "-y", action="store_true", help="Auto-confirm warnings")

    p_batch = sub.add_parser("batch", help="Generate a range of chapters")
    p_batch.add_argument("outline", help="Outline file path")
    p_batch.add_argument("start", type=int)
    p_batch.add_argument("end", type=int)
    p_batch.add_argument("--yes", "-y", action="store_true", help="Auto-confirm warnings")

    p_init = sub.add_parser("init", help="Initialize project (index settings, generate world summary)")

    p_reprocess = sub.add_parser("reprocess", help="Re-extract state and re-index a chapter after manual edits")
    p_reprocess.add_argument("chapter", type=int, help="Chapter number")

    p_reindex = sub.add_parser("reindex", help="Rebuild LightRAG index from setting docs + all chapters")
    p_reindex.add_argument("--clean", action="store_true", help="Delete existing lightrag_data before rebuilding")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {"write": cmd_write, "batch": cmd_batch, "init": cmd_init, "reprocess": cmd_reprocess, "reindex": cmd_reindex}[args.command](args)


if __name__ == "__main__":
    main()
