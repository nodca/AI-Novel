"""Stage 1: Outline precheck + scene planning with assertion-based fact checking."""
import json
import logging

logger = logging.getLogger(__name__)

ASSERTION_EXTRACT_PROMPT = """\
从以下章节细纲中提取所有可核对的事实断言，分为两类：

1. 认知类：某角色知道/不知道/震惊于某事
2. 事实类：某事件的时间、地点、参与者、结果等具体细节

第{chapter_number}章：{title}
出场人物：{characters}
核心事件：
{events}
开头：{opening}
中间：{middle}
结尾：{ending}
伏笔：{foreshadows}

输出JSON数组，每条断言包含：
- statement：断言内容
- type：cognition（认知类）或 fact（事实类）
- related_characters：相关角色列表
- search_query：用于检索历史正文的查询语句

只提取需要与前文核对的断言，不要提取纯粹的新剧情。输出5-15条。
[{{"statement":"...","type":"cognition/fact","related_characters":["..."],"search_query":"..."}}]
"""

ASSERTION_VERIFY_PROMPT = """\
你是一个小说一致性核查员。请逐条判断以下断言与已有证据是否冲突。

【待核查断言】
{assertions_text}

【角色认知记录（CharacterKnowledge）】
{knowledge_context}

【章节摘要】
{summary_context}

【LightRAG检索结果】
{rag_context}

对每条断言判定：support（证据支持）、conflict（与证据冲突）、unknown（无足够证据）。
冲突的断言请给出修正建议。

输出JSON数组：
[{{"index":0,"verdict":"support/conflict/unknown","severity":"error/warning","expected":"对正文的约束（仅conflict时填写）","evidence":"证据来源描述"}}]

规则：
- 认知类conflict（如"角色早已知道却写震惊"）→ severity=error
- 事实类conflict（细节不符）→ severity=warning（小出入）或error（重大矛盾）
- support/unknown → severity 留空
"""

PRECHECK_PROMPT = """\
你是一个小说场景规划师。请根据以下信息将本章拆分为2-4个场景，输出Scene Contract。

## 输入信息

【当前章节细纲】
第{chapter_number}章：{title}
出场人物：{characters}
核心事件：
{events}
开头：{opening}
中间：{middle}
结尾：{ending}
伏笔：{foreshadows}
禁止事项：{forbidden}
目标字数：{word_count}

【角色当前状态】
{character_state}

【角色认知】
{knowledge_context}

【角色关系】
{relationship_context}

【伏笔状态】
{foreshadow_context}

【分层摘要】
{summary_context}

【LightRAG检索结果】
{rag_context}

【事实锚点（必须对齐）】
{fact_anchors}

## 输出格式（严格JSON）
{{
  "scenes": [
    {{
      "scene_number": 1,
      "scene_type": "场景类型，必填。可选值：action(动作/战斗), confrontation(对峙/打脸/文斗), reward(奖励/清点/升级), exposition(解谜/情报/设定展开), daily(日常/互动/感情戏), transition(过渡/赶路/铺垫)",
      "pov_character": "POV角色名",
      "pov_goal": "POV角色在本场景的当前动机/目标（例如：想弄清对方身份、想安全撤离、想炫耀实力）",
      "characters": ["角色1", "角色2"],
      "must_events": ["必须发生的事件"],
      "forbidden_facts": ["不能透露的信息"],
      "must_align_facts": [],
      "required_foreshadows": {{"plant": [], "advance": [], "resolve": []}},
      "reader_emotion_target": "希望读者在此场景产生的情绪（如：紧张刺激、极度爽快、好奇探索、温馨放松等）",
      "core_focus": "本场景的描写重心（高压场景写核心冲突/破局点，低压场景写环境氛围/角色互动细节）",
      "word_count": 800,
      "retrieval_queries": {{
        "narrative": ["叙事检索查询"],
        "setting": ["设定检索查询（可为空数组）"]
      }}
    }}
  ]
}}

注意：must_align_facts 请从【事实锚点】中选取与该场景相关的条目（每场景最多8条），格式为：
{{"statement":"事实断言","expected":"对正文的约束","severity":"error/warning","evidence":"证据来源"}}
"""


def run_precheck(chapter_info: dict, chapter_number: int, session, llm_client, rag_manager) -> dict:
    """Run assertion-based precheck + scene planning. Returns dict with 'contradictions' and 'scenes'."""
    from db.queries import (get_characters, get_pov_knowledge, get_relationships,
                            get_foreshadows_for_chapter, get_summaries)
    from utils.text import extract_json

    characters = chapter_info.get("characters", [])
    events_text = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(chapter_info.get("events", [])))

    # === Step 1: Extract assertions from outline ===
    logger.info("Step 1: Extracting assertions from outline...")
    assertions = _extract_assertions(chapter_info, chapter_number, llm_client)
    logger.info(f"Extracted {len(assertions)} assertions")

    # === Step 2: Gather DB context ===
    chars = get_characters(session, characters or None)
    char_state = "\n".join(
        f"- {c.name}：位置={c.location or '未知'}，状态={c.physical_state or '正常'}，心理={c.mental_state or '正常'}"
        for c in chars
    ) or "（无角色数据）"

    # CharacterKnowledge for all outline characters
    knowledge_lines = []
    for char_name in characters:
        certain = get_pov_knowledge(session, char_name, ("certain",))
        suspect = get_pov_knowledge(session, char_name, ("suspect",))
        if certain or suspect:
            knowledge_lines.append(f"【{char_name}的认知】")
            for k in certain[:15]:
                knowledge_lines.append(f"  [确知] {k.fact}（第{k.learned_chapter}章）")
            for k in suspect[:8]:
                knowledge_lines.append(f"  [怀疑] {k.fact}（{k.source}，第{k.learned_chapter}章）")
    knowledge_context = "\n".join(knowledge_lines) or "（无认知数据）"

    rels = get_relationships(session, characters)
    rel_context = "\n".join(
        f"- {r.from_character} → {r.to_character}：{r.type}（亲密度{r.intimacy}）{r.description or ''}"
        for r in rels
    ) or "（无关系数据）"

    foreshadows = get_foreshadows_for_chapter(session, chapter_number)
    fs_lines = []
    for key, label in [("must_resolve", "必须回收"), ("overdue", "逾期"), ("upcoming", "即将到期"), ("active", "活跃")]:
        for f in foreshadows.get(key, []):
            fs_lines.append(f"- [{label}] {f.title}：{f.content or ''}")
    foreshadow_context = "\n".join(fs_lines) or "（无伏笔数据）"

    summaries = get_summaries(session, chapter_number)
    summary_parts = []
    if summaries.get("global_summary"):
        summary_parts.append(f"全局摘要：{summaries['global_summary'].content}")
    if summaries.get("arc_summary"):
        summary_parts.append(f"弧摘要：{summaries['arc_summary'].content}")
    for s in summaries.get("recent_chapters", []):
        summary_parts.append(f"第{s.scope_start}章：{s.content[:200]}")
    summary_context = "\n".join(summary_parts) or "（无摘要数据）"

    # === Step 3: Verify assertions (batch DB + grouped RAG) ===
    logger.info("Step 3: Verifying assertions...")
    contradictions, fact_anchors = _verify_assertions(
        assertions, knowledge_context, summary_context, session, llm_client, rag_manager
    )
    logger.info(f"Found {len(contradictions)} contradictions, {len(fact_anchors)} fact anchors")

    # General RAG context for scene planning
    rag_context = ""
    if rag_manager:
        queries = characters + chapter_info.get("events", [])[:3]
        query_text = "；".join(queries)
        if query_text:
            rag_context = rag_manager.query(query_text) or "（无检索结果）"

    # === Step 4: Scene planning with fact anchors ===
    logger.info("Step 4: Scene planning...")
    fact_anchors_text = json.dumps(fact_anchors, ensure_ascii=False, indent=2) if fact_anchors else "（无事实锚点）"

    prompt = PRECHECK_PROMPT.format(
        chapter_number=chapter_number,
        title=chapter_info.get("title", ""),
        characters="、".join(characters),
        events=events_text or "（无）",
        opening=chapter_info.get("opening", ""),
        middle=chapter_info.get("middle", ""),
        ending=chapter_info.get("ending", ""),
        foreshadows=chapter_info.get("foreshadows", ""),
        forbidden="、".join(chapter_info.get("forbidden", [])) or "（无）",
        word_count=chapter_info.get("word_count", 2500),
        character_state=char_state,
        knowledge_context=knowledge_context,
        relationship_context=rel_context,
        foreshadow_context=foreshadow_context,
        summary_context=summary_context,
        rag_context=rag_context or "（无检索结果）",
        fact_anchors=fact_anchors_text,
    )

    resp = llm_client.call_sonnet(prompt)
    result = extract_json(resp)

    if not result.get("scenes"):
        logger.warning("Scene planner returned no scenes, using fallback single scene")
        result["scenes"] = [_fallback_scene(chapter_info, chapter_number)]

    # Tag chapter number + ensure must_align_facts exists
    for sc in result.get("scenes", []):
        sc["_chapter_number"] = chapter_number
        if not sc.get("must_align_facts"):
            sc["must_align_facts"] = []

    result["contradictions"] = contradictions
    return result


def _extract_assertions(chapter_info: dict, chapter_number: int, llm_client) -> list:
    """Extract verifiable assertions from outline."""
    from utils.text import extract_json
    events_text = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(chapter_info.get("events", [])))
    prompt = ASSERTION_EXTRACT_PROMPT.format(
        chapter_number=chapter_number,
        title=chapter_info.get("title", ""),
        characters="、".join(chapter_info.get("characters", [])),
        events=events_text or "（无）",
        opening=chapter_info.get("opening", ""),
        middle=chapter_info.get("middle", ""),
        ending=chapter_info.get("ending", ""),
        foreshadows=chapter_info.get("foreshadows", ""),
    )
    resp = llm_client.call_sonnet(prompt, max_tokens=2048)
    # Parse as JSON array
    start = resp.find("[")
    end = resp.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            arr = json.loads(resp[start:end])
            return arr if isinstance(arr, list) else []
        except json.JSONDecodeError:
            pass
    return []


def _verify_assertions(assertions: list, knowledge_context: str, summary_context: str,
                        session, llm_client, rag_manager) -> tuple:
    """Verify assertions against DB + RAG. Returns (contradictions, fact_anchors)."""
    if not assertions:
        return [], []

    # Per-assertion RAG: parallel async queries
    per_assertion_evidence = {}
    if rag_manager:
        query_items = [(i, a.get("search_query", "")) for i, a in enumerate(assertions)]
        query_items = [(i, q) for i, q in query_items if q]
        if query_items:
            indices, queries = zip(*query_items)
            results = rag_manager.batch_query_parallel(list(queries))
            for idx, result in zip(indices, results):
                if result:
                    per_assertion_evidence[idx] = result[:1500]

    # Build assertions text with per-assertion evidence attached
    assertion_lines = []
    for i, a in enumerate(assertions):
        line = f"[{i}] ({a.get('type','fact')}) {a.get('statement','')}"
        evidence = per_assertion_evidence.get(i)
        if evidence:
            line += f"\n    检索证据：{evidence}"
        assertion_lines.append(line)
    assertions_text = "\n".join(assertion_lines)

    prompt = ASSERTION_VERIFY_PROMPT.format(
        assertions_text=assertions_text,
        knowledge_context=knowledge_context,
        summary_context=summary_context,
        rag_context="（证据已附在各断言下方）",
    )
    resp = llm_client.call_sonnet(prompt, max_tokens=2048)

    # Parse verification results
    start = resp.find("[")
    end = resp.rfind("]") + 1
    verdicts = []
    if start >= 0 and end > start:
        try:
            verdicts = json.loads(resp[start:end])
        except json.JSONDecodeError:
            pass

    contradictions = []
    fact_anchors = []
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        idx = v.get("index", -1)
        verdict = v.get("verdict", "unknown")
        assertion = assertions[idx] if 0 <= idx < len(assertions) else {}

        key = f"A{idx}"
        if verdict == "conflict":
            severity = v.get("severity", "warning")
            if severity not in ("error", "warning"):
                severity = "warning"
            contradictions.append({
                "key": key,
                "description": assertion.get("statement", ""),
                "suggestion": v.get("expected", ""),
                "severity": severity,
            })
            fact_anchors.append({
                "key": key,
                "statement": assertion.get("statement", ""),
                "expected": v.get("expected", ""),
                "severity": severity,
                "evidence": v.get("evidence", ""),
            })
        elif verdict == "support" and v.get("evidence"):
            fact_anchors.append({
                "key": key,
                "statement": assertion.get("statement", ""),
                "expected": assertion.get("statement", ""),
                "severity": "info",
                "evidence": v.get("evidence", ""),
            })

    return contradictions, fact_anchors


def _fallback_scene(chapter_info: dict, chapter_number: int) -> dict:
    """Fallback: single scene covering entire chapter."""
    return {
        "scene_number": 1,
        "pov_character": chapter_info.get("characters", [""])[0] if chapter_info.get("characters") else "",
        "characters": chapter_info.get("characters", []),
        "must_events": chapter_info.get("events", []),
        "forbidden_facts": [],
        "must_align_facts": [],
        "required_foreshadows": {},
        "scene_type": "transition",
        "pov_goal": "推进主线",
        "reader_emotion_target": "期待后续",
        "core_focus": "平稳叙事",
        "word_count": chapter_info.get("word_count", 2500),
        "retrieval_queries": {"narrative": [], "setting": []},
        "_chapter_number": chapter_number,
    }
