"""V1 → V2 migration: import PostgreSQL data to SQLite + index chapters to LightRAG."""
import os
import sys
import glob
import json
import logging
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _to_str(val):
    """Convert list/dict to JSON string, pass through strings."""
    if val is None:
        return ""
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def migrate(config_path: str, v1_db_url: str, v1_chapters_dir: str):
    """Run full migration from V1 to V2."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Init V2 DB
    from db.database import get_engine, init_db, get_session
    v2_engine = get_engine(config)
    init_db(v2_engine)
    v2_session = get_session(v2_engine)

    # Connect V1 DB
    v1_engine = create_engine(v1_db_url)
    V1Session = sessionmaker(bind=v1_engine)
    v1_session = V1Session()

    try:
        # Migrate characters
        rows = v1_session.execute(text("SELECT * FROM characters")).mappings().all()
        logger.info(f"Migrating {len(rows)} characters...")
        from db.models import Character
        for r in rows:
            existing = v2_session.query(Character).filter_by(name=r["name"]).first()
            if existing:
                continue
            v2_session.add(Character(
                name=r["name"], role_type=_to_str(r.get("role_type", "")),
                gender=_to_str(r.get("gender", "")), age=_to_str(r.get("age", "")),
                appearance=_to_str(r.get("appearance", "")), personality=_to_str(r.get("personality", "")),
                background=_to_str(r.get("background", "")), location=_to_str(r.get("location", "")),
                physical_state=_to_str(r.get("physical_state", "")), mental_state=_to_str(r.get("mental_state", "")),
                cultivation_stage=_to_str(r.get("cultivation_stage", "")),
                items=_to_str(r.get("items", "")), abilities=_to_str(r.get("abilities", "")),
                speech_style=_to_str(r.get("speech_style", "")),
                dialogue_examples=_to_str(r.get("dialogue_examples", "")),
                is_active=r.get("is_active", True),
            ))

        # Migrate relationships
        rows = v1_session.execute(text("SELECT * FROM character_relationships")).mappings().all()
        logger.info(f"Migrating {len(rows)} relationships...")
        from db.models import CharacterRelationship
        for r in rows:
            v2_session.add(CharacterRelationship(
                from_character=r["character_from"], to_character=r["character_to"],
                type=_to_str(r.get("relationship_type", "")), intimacy=r.get("intimacy_level", 50),
                description=_to_str(r.get("description", "")),
            ))

        # Migrate established facts → CharacterKnowledge
        try:
            rows = v1_session.execute(text("SELECT * FROM established_facts")).mappings().all()
            logger.info(f"Migrating {len(rows)} facts → CharacterKnowledge...")
            from db.models import CharacterKnowledge
            for r in rows:
                known_by = r.get("known_by", "[]")
                if isinstance(known_by, str):
                    try:
                        known_by = json.loads(known_by)
                    except json.JSONDecodeError:
                        known_by = [known_by]
                for char_name in known_by:
                    v2_session.add(CharacterKnowledge(
                        character=char_name, fact=r["fact"],
                        source="migrated", learned_chapter=0,
                        confidence="certain",
                    ))
        except Exception as e:
            logger.warning(f"No established_fact table or migration failed: {e}")

        # Migrate foreshadows
        try:
            rows = v1_session.execute(text("SELECT * FROM foreshadows")).mappings().all()
            logger.info(f"Migrating {len(rows)} foreshadows...")
            from db.models import Foreshadow
            for r in rows:
                v2_session.add(Foreshadow(
                    title=r["title"], content=_to_str(r.get("content", "")),
                    hint_text=_to_str(r.get("hint_text", "")),
                    chapter_planted=r.get("plant_chapter", 0),
                    chapter_resolved=r.get("actual_resolve_chapter"),
                    target_resolve_chapter=r.get("target_resolve_chapter"),
                    is_long_term=r.get("is_long_term", False),
                    importance=r.get("importance", 0.5),
                    strength=r.get("strength", 5), subtlety=r.get("subtlety", 5),
                    related_characters=_to_str(r.get("related_characters", "[]")),
                    category=_to_str(r.get("category", "")),
                    status=_to_str(r.get("status", "planted")),
                ))
        except Exception as e:
            logger.warning(f"Foreshadow migration failed: {e}")

        # Migrate summaries
        try:
            rows = v1_session.execute(text("SELECT * FROM summaries")).mappings().all()
            logger.info(f"Migrating {len(rows)} summaries...")
            from db.models import Summary
            for r in rows:
                v2_session.add(Summary(
                    level=r["level"], scope_start=r.get("scope_start"),
                    scope_end=r.get("scope_end"), content=r.get("content", ""),
                ))
        except Exception as e:
            logger.warning(f"Summary migration failed: {e}")

        v2_session.commit()
        logger.info("DB migration complete")

    except Exception as e:
        v2_session.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        v1_session.close()
        v2_session.close()

    # Index chapters to LightRAG
    if v1_chapters_dir and os.path.isdir(v1_chapters_dir):
        logger.info("Indexing chapters to LightRAG...")
        from rag.lightrag_manager import LightRAGManager
        rag = LightRAGManager(config)
        files = sorted(glob.glob(os.path.join(v1_chapters_dir, "*.md")))
        for f in files:
            with open(f, "r", encoding="utf-8") as fh:
                text_content = fh.read()
            try:
                rag.index_text(text_content)
                logger.info(f"Indexed: {os.path.basename(f)}")
            except Exception as e:
                logger.warning(f"Failed to index {f}: {e}")

    logger.info("Migration complete!")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python migrate_v1.py <config.yaml> <v1_db_url> <v1_chapters_dir>")
        print("Example: python migrate_v1.py config.yaml postgresql://postgres:postgres@localhost:5432/novel_generator ./chapters")
        sys.exit(1)
    migrate(sys.argv[1], sys.argv[2], sys.argv[3])
