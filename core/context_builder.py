"""Context builder - assembles prompt for each scene with POV sandbox and token budget."""
import json
import logging

logger = logging.getLogger(__name__)

SEP = "\n\n"


def build_scene_prompt(
    scene_contract: dict,
    session,
    rag_manager,
    style_guide: str,
    bridge_memo: str,
    config: dict,
) -> str:
    """Build the full prompt for a single scene, respecting token budget and POV sandbox."""
    from db.queries import (get_characters, get_pov_knowledge, get_relationships,
                            get_foreshadows_for_chapter, get_summaries, get_world_summary)
    from utils.text import count_tokens_approx

    max_tokens = config.get("generation", {}).get("max_input_tokens_per_scene", 12000)
    pov = scene_contract.get("pov_character", "")
    chars = scene_contract.get("characters", [])
    chapter_num = scene_contract.get("_chapter_number", 0)
    voice_limit = config.get("generation", {}).get("voice_samples_limit", 4)

    # === Build layers ===
    must_parts = []
    must_parts.append(_build_system_role())
    must_parts.append(_build_style_guide(style_guide))
    must_parts.append(_build_world_summary(session))
    must_parts.append(_build_scene_contract(scene_contract))
    must_parts.append(_build_fact_anchors(scene_contract))
    must_parts.append(_build_character_states(session, chars, pov, voice_limit))
    must_parts.append(_build_bridge_memo(bridge_memo))

    important_parts = []
    important_parts.append(_build_pov_knowledge(session, pov))
    important_parts.append(_build_relationships(session, chars))
    important_parts.append(_build_foreshadow_instructions(session, scene_contract, chapter_num))
    important_parts.append(_build_summaries(session, chapter_num))

    nice_parts = []
    if rag_manager:
        nice_parts.extend(_build_rag_results(rag_manager, scene_contract))

    # === Assemble with budget ===
    must_text = SEP.join(p for p in must_parts if p)
    important_text = SEP.join(p for p in important_parts if p)
    nice_text = SEP.join(p for p in nice_parts if p)

    must_tokens = count_tokens_approx(must_text)
    remaining = max_tokens - must_tokens

    if remaining <= 0:
        logger.warning(f"Must layer alone exceeds budget ({must_tokens} tokens)")
        return must_text

    imp_tokens = count_tokens_approx(important_text)
    if imp_tokens <= remaining:
        remaining -= imp_tokens
        nice_tokens = count_tokens_approx(nice_text)
        if nice_tokens <= remaining:
            return SEP.join([must_text, important_text, nice_text])
        else:
            trimmed_nice = _trim_to_budget(nice_parts, remaining)
            return SEP.join(filter(None, [must_text, important_text, trimmed_nice]))
    else:
        logger.warning("Important layer exceeds remaining budget, trimming")
        trimmed_imp = _trim_to_budget(important_parts, remaining)
        return SEP.join(filter(None, [must_text, trimmed_imp]))


def generate_bridge_memo(prev_scene_text: str, llm_client) -> str:
    """Generate a structured bridge memo from the previous scene."""
    if not prev_scene_text:
        return ""
    prompt = (
        "请从以下场景文本中提取衔接信息，用150-300字输出：\n\n"
        "1. 上个场景结尾：最后发生了什么\n"
        "2. 未解决的张力：有什么悬而未决的事\n"
        "3. 下个场景铺垫：接下来需要衔接什么\n\n"
        "场景文本（末尾部分）：\n"
        f"{prev_scene_text[-2000:]}\n\n"
        "直接输出衔接信息，不要输出JSON。"
    )
    return llm_client.call_sonnet(prompt, max_tokens=512)


# === Layer builders ===

def _build_system_role() -> str:
    return ("你是一位专业的网络小说作家。请根据以下信息写作场景正文。\n"
            "重要约束：禁止编造前文未发生的具体细节（伤痕、物品状态、具体战绩、身体特征）。"
            "角色对白中引用过去事件时，只使用上下文中明确提供的信息；不确定的用模糊表达带过，不要捏造具体情节。\n"
            "文笔约束：禁止使用'不是……而是……'这类模板句式。")


def _build_style_guide(style_guide: str) -> str:
    if not style_guide:
        return ""
    return "【写作风格】\n" + style_guide[:5000]


def _build_world_summary(session) -> str:
    from db.queries import get_world_summary
    ws = get_world_summary(session)
    if not ws:
        return ""
    return "【世界观】\n" + ws.content


def _build_bridge_memo(bridge_memo: str) -> str:
    if not bridge_memo:
        return ""
    return "【前场景衔接】\n" + bridge_memo


def _build_scene_contract(sc: dict) -> str:
    lines = ["【场景合同 - 场景" + str(sc.get("scene_number", "?")) + "】"]
    lines.append("POV角色：" + sc.get("pov_character", "未指定"))
    chars = sc.get("characters", [])
    lines.append("出场角色：" + "、".join(chars))
    lines.append("节奏：" + sc.get("tone_target", ""))
    lines.append("字数：" + str(sc.get("word_count", 800)) + "字")

    events = sc.get("must_events", [])
    if events:
        lines.append("必须完成的事件：")
        for i, e in enumerate(events, 1):
            lines.append("  " + str(i) + ". " + e)

    forbidden = sc.get("forbidden_facts", [])
    if forbidden:
        lines.append("禁止透露：" + "；".join(forbidden))

    return "\n".join(lines)


def _build_fact_anchors(sc: dict) -> str:
    facts = sc.get("must_align_facts", [])
    if not facts:
        return ""
    lines = ["【事实锚点 - 写作时必须对齐】"]
    for f in facts[:8]:
        sev = f.get("severity", "warning")
        tag = "[必须]" if sev == "error" else "[建议]"
        key = f.get("key", "?")
        lines.append(f"{tag} [{key}] {f.get('statement', '')}")
        expected = f.get("expected", "")
        if expected:
            lines.append(f"  → 要求：{expected}")
        evidence = f.get("evidence", "")
        if evidence:
            lines.append(f"  → 依据：{evidence}")
    return "\n".join(lines)


def _build_character_states(session, chars: list, pov: str, voice_limit: int) -> str:
    from db.queries import get_characters
    db_chars = get_characters(session, chars)
    if not db_chars:
        return ""

    lines = ["【出场角色】"]
    for c in db_chars:
        is_pov = (c.name == pov)
        parts = [("[POV] " if is_pov else "") + c.name + "（" + (c.role_type or "") + "）"]
        if c.personality:
            parts.append("  性格：" + c.personality)
        if c.speech_style:
            parts.append("  说话风格：" + c.speech_style)
        if is_pov:
            if c.location:
                parts.append("  位置：" + c.location)
            if c.physical_state:
                parts.append("  身体状态：" + c.physical_state)
            if c.mental_state:
                parts.append("  心理状态：" + c.mental_state)
            if c.items:
                parts.append("  持有物品：" + c.items)
            if c.abilities:
                parts.append("  能力：" + c.abilities)
        else:
            if c.appearance:
                parts.append("  外貌：" + c.appearance)
            if c.location:
                parts.append("  位置：" + c.location)

        samples = _get_voice_samples(c, voice_limit)
        if samples:
            parts.append("  对话示例：")
            for s in samples:
                parts.append("    「" + s.get("text", "") + "」")

        lines.append("\n".join(parts))
    return "\n".join(lines)


def _get_voice_samples(character, limit: int) -> list:
    if not character.voice_samples:
        return []
    try:
        samples = json.loads(character.voice_samples)
    except (json.JSONDecodeError, TypeError):
        return []
    if not samples:
        return []
    recent = samples[-2:] if len(samples) >= 2 else samples
    typical = samples[:max(1, limit - len(recent))]
    seen = set()
    result = []
    for s in recent + typical:
        text = s.get("text", "")
        if text not in seen:
            seen.add(text)
            result.append(s)
    return result[:limit]


def _build_pov_knowledge(session, pov: str) -> str:
    if not pov:
        return ""
    from db.queries import get_pov_knowledge
    certain = get_pov_knowledge(session, pov, ("certain",))
    suspect = get_pov_knowledge(session, pov, ("suspect",))
    if not certain and not suspect:
        return ""
    lines = ["【" + pov + "的认知沙箱】"]
    lines.append('注意：以下是该角色已知的信息，不要重复写角色"发现""意识到""推测出"这些已知内容的过程。已知即已知，直接体现在行为和判断中。')
    if certain:
        lines.append("确知的事实：")
        for k in certain[:15]:
            lines.append("  - " + k.fact)
    if suspect:
        lines.append("怀疑/隐约感觉（只能用暗示表达，不能确定性断言）：")
        for k in suspect[:10]:
            lines.append("  - " + k.fact + "（来源：" + k.source + "，第" + str(k.learned_chapter) + "章）")
    return "\n".join(lines)


def _build_relationships(session, chars: list) -> str:
    from db.queries import get_relationships
    rels = get_relationships(session, chars)
    if not rels:
        return ""
    lines = ["【角色关系】"]
    for r in rels:
        lines.append("- " + r.from_character + " → " + r.to_character + "：" + r.type
                      + "（亲密度" + str(r.intimacy) + "）" + (r.description or ""))
    return "\n".join(lines)


def _build_foreshadow_instructions(session, sc: dict, chapter_num: int) -> str:
    required = sc.get("required_foreshadows", {})
    if not any(required.values()):
        return ""
    lines = ["【伏笔指令】"]
    for action, items in required.items():
        if items:
            lines.append("- " + action + "：" + "；".join(items))
    return "\n".join(lines)


def _build_summaries(session, chapter_num: int) -> str:
    from db.queries import get_summaries
    summaries = get_summaries(session, chapter_num)
    parts = []
    if summaries.get("global_summary"):
        parts.append("【全局摘要】\n" + summaries["global_summary"].content)
    if summaries.get("arc_summary"):
        parts.append("【弧摘要】\n" + summaries["arc_summary"].content)
    recent = summaries.get("recent_chapters", [])
    if recent:
        lines = ["【近章摘要】"]
        for s in recent[-3:]:
            lines.append("第" + str(s.scope_start) + "章：" + s.content[:200])
        parts.append("\n".join(lines))
    return SEP.join(parts)


def _build_rag_results(rag_manager, sc: dict) -> list:
    parts = []
    queries = sc.get("retrieval_queries", {})
    narrative_qs = queries.get("narrative", [])
    if narrative_qs:
        results = rag_manager.batch_query(narrative_qs)
        combined = "\n".join(r for r in results if r)
        if combined:
            parts.append("【相关历史叙事】\n" + combined)
    setting_qs = queries.get("setting", [])
    if setting_qs:
        results = rag_manager.batch_query(setting_qs)
        combined = "\n".join(r for r in results if r)
        if combined:
            parts.append("【相关设定】\n" + combined)
    return parts


def _trim_to_budget(parts: list, budget_tokens: int) -> str:
    from utils.text import count_tokens_approx
    result = []
    used = 0
    for p in parts:
        if not p:
            continue
        t = count_tokens_approx(p)
        if used + t <= budget_tokens:
            result.append(p)
            used += t
        else:
            break
    return SEP.join(result)
