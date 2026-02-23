"""Stage 3: Postprocessing - extract state, write DB, index LightRAG, save file."""
import os
import re
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """\
请分析以下章节文本，一次性提取所有结构化信息，以JSON格式输出（不要输出任何其他内容）：
{{
  "character_changes": [
    {{"name": "角色名", "field": "字段名", "value": "新值"}}
  ],
  "relationship_changes": [
    {{"from": "角色A", "to": "角色B", "type": "关系类型", "intimacy_delta": 0, "description": "描述"}}
  ],
  "new_characters": [
    {{"name": "新角色", "role_type": "supporting", "gender": "", "personality": "", "appearance": ""}}
  ],
  "knowledge_updates": [
    {{"character": "角色名", "fact": "事实内容", "source": "witnessed/told/inferred", "confidence": "certain/suspect/guess"}}
  ],
  "knowledge_triples": [
    {{"subject": "主体", "predicate": "谓词", "object": "客体", "subject_type": "类型", "object_type": "类型"}}
  ],
  "foreshadows": {{
    "planted": [
      {{"title": "伏笔标题", "content": "描述", "hint_text": "原文暗示", "target_resolve_chapter": null, "importance": 0.5, "related_characters": ["角色1"], "category": "identity/mystery/item/relationship/event"}}
    ],
    "resolved": [
      {{"title": "从下方已有伏笔列表中选择的标题（必须完全匹配）", "resolution_text": "回收方式"}}
    ]
  }},
  "voice_samples": [
    {{"character": "角色名", "text": "典型对话原文", "context": "对话场景简述"}}
  ],
  "chapter_summary": "本章摘要（200-400字）"
}}

字段说明：
- character_changes.field: location/physical_state/mental_state/cultivation_stage/items/abilities
- knowledge_updates: 本章中角色新获知的信息，注意区分source和confidence
- voice_samples: 提取每个出场角色最有代表性的1-2句对话

伏笔提取规则（严格遵守）：
- planted: 只提取正文中【明确留下悬念、未解之谜、未完成的事件线索】的内容。普通叙事细节（角色的日常行为、已完成的动作、性格展示）不算伏笔。每章最多提取3条。
- resolved: 从下方"已有伏笔"列表中，找出在本章正文中被明确回收/解答/揭示的伏笔，title必须与列表中完全一致。
- 不要重复种植已有伏笔列表中已存在的同类伏笔。

已有伏笔（planted状态）：
{existing_foreshadows}

当前章节号：{chapter_number}
章节文本：
{chapter_text}
"""


def run_postprocess(chapter_number: int, chapter_text: str, chapter_title: str,
                    novel_dir: str, session, llm_client, rag_manager, config: dict):
    """Run full postprocessing pipeline with transaction safety."""
    gen_cfg = config.get("generation", {}) if config else {}
    voice_limit = int(gen_cfg.get("voice_samples_limit", 10))
    arc_interval = int(gen_cfg.get("summary_arc_interval", 10))

    pending_dir = os.path.join(novel_dir, ".pending")
    os.makedirs(pending_dir, exist_ok=True)
    pending_file = os.path.join(pending_dir, "ch" + str(chapter_number) + "_extract.json")
    chapter_hash = hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()

    # 3a. Extract (or load from pending)
    if os.path.exists(pending_file):
        logger.info("Loading existing extraction from " + pending_file)
        with open(pending_file, "r", encoding="utf-8") as f:
            pending_payload = json.load(f)
        data, reused = _load_pending_extract(pending_payload, chapter_hash)
        if not reused:
            logger.info("Pending extract does not match current chapter text, regenerating extraction")
            data = _extract_data(chapter_number, chapter_text, llm_client, session)
            _save_pending_extract(pending_file, chapter_hash, data)
    else:
        data = _extract_data(chapter_number, chapter_text, llm_client, session)
        _save_pending_extract(pending_file, chapter_hash, data)

    if not data:
        logger.error("Extraction returned empty data")
        return

    # 3b. Validate extracted data before DB write
    extract_errors = _validate_extract_data(data)
    if extract_errors:
        raise ValueError("Extract validation failed: " + "; ".join(extract_errors))

    # 3b. Write DB (single transaction)
    try:
        _write_db(session, chapter_number, data, voice_limit=voice_limit, arc_interval=arc_interval)
        session.commit()
        logger.info("DB write committed")
    except Exception as e:
        session.rollback()
        logger.error("DB write failed, rolled back: " + str(e))
        raise

    # 3c. LightRAG index
    if rag_manager:
        from rag.indexer import index_chapter
        try:
            index_chapter(rag_manager, chapter_number, chapter_text, novel_dir)
            logger.info("LightRAG index complete")
        except Exception as e:
            logger.warning("LightRAG indexing failed (will retry later): " + str(e))

    # 3d. Save chapter file + cleanup
    filepath = _save_chapter(novel_dir, chapter_number, chapter_title, chapter_text)
    if os.path.exists(pending_file):
        os.remove(pending_file)
    logger.info("Chapter saved: " + filepath)


def _extract_data(chapter_number: int, chapter_text: str, llm_client, session=None) -> dict:
    logger.info("Extracting structured data from chapter...")
    existing_fs = ""
    if session:
        from db.models import Foreshadow
        planted = session.query(Foreshadow).filter_by(status="planted").all()
        if planted:
            existing_fs = "\n".join(f"- [{f.chapter_planted}] {f.title}" for f in planted)
    if not existing_fs:
        existing_fs = "（无）"
    prompt = EXTRACT_PROMPT.format(
        chapter_number=chapter_number,
        chapter_text=chapter_text[:6000],
        existing_foreshadows=existing_fs,
    )
    resp = llm_client.call_sonnet(prompt)
    from utils.text import extract_json
    return extract_json(resp)


def _save_pending_extract(path: str, chapter_hash: str, data: dict):
    payload = {
        "chapter_hash": chapter_hash,
        "extract": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_pending_extract(payload: dict, chapter_hash: str):
    if isinstance(payload, dict) and "chapter_hash" in payload and "extract" in payload:
        if payload.get("chapter_hash") == chapter_hash:
            return payload.get("extract", {}), True
        return {}, False
    # Backward compatibility for old pending format (raw extract without hash)
    return {}, False


def _validate_extract_data(data: dict) -> list:
    errors = []
    allowed_fields = {"location", "physical_state", "mental_state", "cultivation_stage", "items", "abilities"}
    allowed_confidence = {"certain", "suspect", "guess"}

    if not isinstance(data, dict):
        return ["extract result is not a JSON object"]

    for key in ("character_changes", "relationship_changes", "new_characters",
                "knowledge_updates", "knowledge_triples", "voice_samples"):
        if key in data and not isinstance(data.get(key), list):
            errors.append(f"{key} must be a list")

    if "foreshadows" in data and not isinstance(data.get("foreshadows"), dict):
        errors.append("foreshadows must be an object")

    for change in data.get("character_changes", []):
        field = change.get("field", "")
        if field and field not in allowed_fields:
            errors.append(f"invalid character_changes.field: {field}")

    for rel in data.get("relationship_changes", []):
        if not rel.get("from") or not rel.get("to"):
            errors.append("relationship_changes item missing from/to")

    for ku in data.get("knowledge_updates", []):
        conf = ku.get("confidence", "certain")
        if conf not in allowed_confidence:
            errors.append(f"invalid confidence level: {conf}")
        if not ku.get("character") or not ku.get("fact"):
            errors.append("knowledge_updates item missing character/fact")

    fs = data.get("foreshadows", {})
    if isinstance(fs, dict):
        for planted in fs.get("planted", []):
            if not planted.get("title"):
                errors.append("foreshadows.planted item missing title")
        for resolved in fs.get("resolved", []):
            if not resolved.get("title"):
                errors.append("foreshadows.resolved item missing title")

    return errors


def _write_db(session, chapter_number: int, data: dict, voice_limit: int, arc_interval: int):
    """Write all extracted data to DB in a single transaction."""
    from db.models import (Character, CharacterRelationship, CharacterKnowledge,
                           KnowledgeTriple, Foreshadow, Summary)

    # Character changes
    for change in data.get("character_changes", []):
        char = session.query(Character).filter_by(name=change.get("name")).first()
        field = change.get("field", "")
        if char and hasattr(char, field):
            setattr(char, field, change.get("value"))

    # New characters
    for nc in data.get("new_characters", []):
        if not session.query(Character).filter_by(name=nc["name"]).first():
            session.add(Character(
                name=nc["name"], role_type=nc.get("role_type", "supporting"),
                gender=nc.get("gender", ""), personality=nc.get("personality", ""),
                appearance=nc.get("appearance", ""),
            ))

    # Relationship changes
    for rel in data.get("relationship_changes", []):
        existing = session.query(CharacterRelationship).filter_by(
            from_character=rel["from"], to_character=rel["to"]
        ).first()
        if existing:
            if rel.get("type"):
                existing.type = rel["type"]
            existing.intimacy = max(0, min(100, existing.intimacy + rel.get("intimacy_delta", 0)))
            if rel.get("description"):
                existing.description = rel["description"]
        else:
            base_intimacy = 50 + rel.get("intimacy_delta", 0)
            session.add(CharacterRelationship(
                from_character=rel["from"], to_character=rel["to"],
                type=rel.get("type", ""),
                intimacy=max(0, min(100, base_intimacy)),
                description=rel.get("description", ""),
            ))

    # Knowledge updates
    for ku in data.get("knowledge_updates", []):
        if not session.query(CharacterKnowledge).filter_by(
            character=ku["character"], fact=ku["fact"]
        ).first():
            session.add(CharacterKnowledge(
                character=ku["character"], fact=ku["fact"],
                source=ku.get("source", "witnessed"),
                learned_chapter=chapter_number,
                confidence=ku.get("confidence", "certain"),
            ))

    # Knowledge triples
    for kt in data.get("knowledge_triples", []):
        subject = kt.get("subject", "")
        predicate = kt.get("predicate", "")
        obj = kt.get("object", "")
        if not subject or not predicate or not obj:
            continue
        existing = session.query(KnowledgeTriple).filter_by(
            subject=subject,
            predicate=predicate,
            object=obj,
            chapter_number=chapter_number,
        ).first()
        if not existing:
            session.add(KnowledgeTriple(
                subject=subject, predicate=predicate, object=obj,
                subject_type=kt.get("subject_type", ""), object_type=kt.get("object_type", ""),
                chapter_number=chapter_number,
            ))

    # Foreshadows
    fs = data.get("foreshadows", {})
    for planted in fs.get("planted", []):
        title = planted.get("title", "")
        if not title:
            continue
        existing = session.query(Foreshadow).filter_by(
            title=title,
            chapter_planted=chapter_number,
        ).first()
        if existing:
            continue
        session.add(Foreshadow(
            title=title, content=planted.get("content", ""),
            hint_text=planted.get("hint_text", ""), chapter_planted=chapter_number,
            target_resolve_chapter=planted.get("target_resolve_chapter"),
            importance=planted.get("importance", 0.5),
            related_characters=json.dumps(planted.get("related_characters", []), ensure_ascii=False),
            category=planted.get("category", ""),
        ))
    for resolved in fs.get("resolved", []):
        f = session.query(Foreshadow).filter_by(title=resolved["title"], status="planted").first()
        if f:
            f.status = "resolved"
            f.chapter_resolved = chapter_number

    # Voice samples
    for vs in data.get("voice_samples", []):
        char = session.query(Character).filter_by(name=vs["character"]).first()
        if char:
            samples = json.loads(char.voice_samples) if char.voice_samples else []
            new_sample = {"chapter": chapter_number, "text": vs["text"], "context": vs.get("context", "")}
            if not any(s.get("chapter") == new_sample["chapter"] and s.get("text") == new_sample["text"] for s in samples):
                samples.append(new_sample)
            char.voice_samples = json.dumps(samples[-max(1, voice_limit):], ensure_ascii=False)

    # Chapter summary
    summary_text = data.get("chapter_summary", "").strip()
    if summary_text:
        existing = session.query(Summary).filter_by(
            level="chapter", scope_start=chapter_number, scope_end=chapter_number
        ).first()
        if existing:
            existing.content = summary_text
        else:
            session.add(Summary(
                level="chapter", scope_start=chapter_number,
                scope_end=chapter_number, content=summary_text,
            ))

    # Arc summary check
    if arc_interval > 0 and chapter_number % arc_interval == 0:
        _update_arc_summary(session, chapter_number, arc_interval)


def _update_arc_summary(session, chapter_number: int, arc_interval: int):
    """Combine chapter summaries into arc summary."""
    from db.models import Summary
    arc_start = chapter_number - arc_interval + 1
    chapters = session.query(Summary).filter(
        Summary.level == "chapter",
        Summary.scope_start >= arc_start,
        Summary.scope_end <= chapter_number,
    ).order_by(Summary.scope_start).all()
    if not chapters:
        return
    combined = "\n".join("第" + str(s.scope_start) + "章：" + s.content for s in chapters)
    existing = session.query(Summary).filter_by(
        level="arc", scope_start=arc_start, scope_end=chapter_number
    ).first()
    if existing:
        existing.content = combined
    else:
        session.add(Summary(level="arc", scope_start=arc_start, scope_end=chapter_number, content=combined))


def _save_chapter(novel_dir: str, chapter_number: int, title: str, content: str) -> str:
    """Save chapter to file."""
    chapters_dir = os.path.join(novel_dir, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)
    safe_title = re.sub(r'[\\/:*?"<>|]', '', title)
    filename = ("第" + str(chapter_number) + "章-" + safe_title + ".md") if safe_title else ("第" + str(chapter_number) + "章.md")
    filepath = os.path.join(chapters_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# 第" + str(chapter_number) + "章 " + title + "\n\n" + content)
    return filepath
