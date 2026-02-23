"""Consistency checker (Stage 2.5) - validates generated chapter before postprocessing."""
import re
import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Issue:
    type: str       # contract|timeline|location|knowledge|foreshadow
    severity: str   # error|warning
    description: str
    location: str = ""
    fix_instruction: str = ""


@dataclass
class ConsistencyReport:
    chapter: int
    issues: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


def _split_scenes(chapter_text: str) -> list:
    parts = [p.strip() for p in re.split(r"\n\s*---+\s*\n", chapter_text) if p.strip()]
    return parts if parts else [chapter_text]


def _extract_keywords(text: str) -> list:
    return [w for w in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text) if len(w) >= 2]


def _parse_json_array(text: str) -> list:
    start = text.find("[")
    end = text.rfind("]") + 1
    if start < 0 or end <= start:
        return []
    try:
        arr = json.loads(text[start:end])
        return arr if isinstance(arr, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def check_contract(chapter_text: str, scene_contracts: list, session, llm_client=None) -> list:
    """Check Scene Contract fulfillment - deterministic lexical checks only."""
    issues = []
    from db.models import Character
    registered_names = {c.name for c in session.query(Character).filter_by(is_active=True).all()}
    scenes = _split_scenes(chapter_text)

    all_contract_chars = set()
    for idx, sc in enumerate(scene_contracts):
        scene_text = scenes[idx] if idx < len(scenes) else ""
        all_contract_chars.update(sc.get("characters", []))
        scene_num = sc.get("scene_number", "?")

        for event in sc.get("must_events", []):
            keywords = _extract_keywords(event)
            if keywords and not any(kw in scene_text for kw in keywords):
                issues.append(Issue(
                    type="contract", severity="warning",
                    description=f"场景{scene_num}: 必须事件可能未体现: {event}",
                    location=f"scene_{scene_num}",
                ))

        for fact in sc.get("forbidden_facts", []):
            keywords = _extract_keywords(fact)
            if keywords and any(kw in scene_text for kw in keywords):
                issues.append(Issue(
                    type="contract", severity="error",
                    description=f"场景{scene_num}: 禁止内容可能泄露: {fact}",
                    location=f"scene_{scene_num}",
                    fix_instruction=f"删除或改写涉及'{fact}'的段落",
                ))

    for name in registered_names:
        if name not in all_contract_chars and name in chapter_text:
            issues.append(Issue(
                type="contract", severity="warning",
                description=f"合同外命名角色出现: {name}",
                location="chapter",
                fix_instruction=f"移除角色'{name}'的出场，或改为匿名背景角色",
            ))

    return issues


def check_semantic(chapter_text: str, scene_contracts: list, session, llm_client) -> list:
    """Combined LLM semantic check: contract fulfillment + fact anchors + POV knowledge. Single call."""
    issues = []
    from db.queries import get_pov_knowledge

    # Build scene info
    scene_sections = []
    scenes = _split_scenes(chapter_text)
    for idx, sc in enumerate(scene_contracts):
        scene_text = scenes[idx] if idx < len(scenes) else ""
        if not scene_text.strip():
            continue
        scene_num = sc.get("scene_number", idx + 1)
        pov = sc.get("pov_character", "")

        section = f"=== 场景{scene_num} (POV: {pov}) ===\n"
        section += f"must_events: {json.dumps(sc.get('must_events', []), ensure_ascii=False)}\n"
        section += f"forbidden_facts: {json.dumps(sc.get('forbidden_facts', []), ensure_ascii=False)}\n"

        facts = [f for f in sc.get("must_align_facts", []) if f.get("severity") in ("error", "warning")]
        if facts:
            section += "fact_anchors:\n"
            for f in facts:
                section += f"  [{f.get('key','?')}] ({f.get('severity','warning')}) {f.get('statement','')} → {f.get('expected','')}\n"

        if pov:
            certain = get_pov_knowledge(session, pov, ("certain",))
            suspect = get_pov_knowledge(session, pov, ("suspect",))
            if certain or suspect:
                section += f"{pov}的认知：\n"
                if certain:
                    section += "  确知：" + "；".join(k.fact for k in certain[:15]) + "\n"
                if suspect:
                    section += "  怀疑：" + "；".join(k.fact for k in suspect[:10]) + "\n"

        section += f"正文：\n{scene_text[:3000]}\n"
        scene_sections.append(section)

    if not scene_sections:
        return issues

    all_scenes_text = "\n".join(scene_sections)

    prompt = f"""一次性检查以下所有场景，输出JSON数组（无问题输出[]）。

检查规则：
1. must_events未体现 → warning
2. forbidden_facts被明示或实质泄露 → error
3. fact_anchors被违反 → 按标注的severity
4. POV认知冲突：suspect被确定性断言→error；不在认知范围的信息被POV使用→error；遗忘关键certain事实→warning

{all_scenes_text}

输出格式（严格JSON数组）：
[{{"type":"contract/fact_anchor/knowledge","severity":"error或warning","description":"问题描述","location":"scene_N","fix_instruction":"修复建议"}}]"""

    resp = llm_client.call_sonnet(prompt, max_tokens=2048)
    for item in _parse_json_array(resp):
        sev = item.get("severity", "warning")
        if sev not in ("error", "warning"):
            sev = "warning"
        issues.append(Issue(
            type=item.get("type", "contract"),
            severity=sev,
            description=item.get("description", ""),
            location=item.get("location", ""),
            fix_instruction=item.get("fix_instruction", ""),
        ))
    return issues


def check_timeline(chapter_text: str, scene_contracts: list) -> list:
    """Deterministic timeline consistency check based on scene order and temporal markers."""
    issues = []
    scenes = _split_scenes(chapter_text)
    phase_patterns = [
        (0, [r"清晨", r"黎明", r"凌晨"]),
        (1, [r"早上", r"早晨"]),
        (2, [r"上午"]),
        (3, [r"中午", r"正午"]),
        (4, [r"下午"]),
        (5, [r"傍晚", r"黄昏"]),
        (6, [r"晚上", r"夜晚", r"入夜"]),
        (7, [r"深夜", r"夜深"]),
    ]
    next_day_markers = [r"次日", r"第二天", r"翌日", r"隔天", r"次晨"]

    day_offset = 0
    last_stamp = -1
    for idx, scene_text in enumerate(scenes):
        scene_num = scene_contracts[idx].get("scene_number", idx + 1) if idx < len(scene_contracts) else idx + 1
        if any(re.search(p, scene_text) for p in next_day_markers):
            day_offset += 1

        phase = None
        for rank, patterns in phase_patterns:
            if any(re.search(p, scene_text) for p in patterns):
                phase = rank
                break
        if phase is None:
            phase = 0 if last_stamp < 0 else (last_stamp % 10)

        stamp = day_offset * 10 + phase
        if last_stamp >= 0 and stamp < last_stamp:
            issues.append(Issue(
                type="timeline",
                severity="warning",
                description=f"场景{scene_num}时间推进疑似倒退（标记 {stamp} < {last_stamp}）",
                location=f"scene_{scene_num}",
                fix_instruction="补充过渡时间描述，或调整时序表达",
            ))
        last_stamp = stamp
    return issues


def check_location(chapter_text: str, characters: list, session) -> list:
    """Check character location continuity. Deterministic."""
    issues = []
    from db.models import Character
    for char_name in characters:
        char = session.query(Character).filter_by(name=char_name, is_active=True).first()
        if not char or not char.location:
            continue
        if char_name in chapter_text and char.location not in chapter_text:
            issues.append(Issue(
                type="location", severity="warning",
                description=f"{char_name}上一章位于'{char.location}'，本章未提及该地点",
            ))
    return issues


def check_foreshadow(scene_contracts: list, session, chapter_number: int) -> list:
    """Check foreshadow state machine validity. Deterministic."""
    issues = []
    from db.models import Foreshadow
    all_fs = session.query(Foreshadow).all()
    fs_map = {f.title: f for f in all_fs}

    for sc in scene_contracts:
        for title in sc.get("required_foreshadows", {}).get("resolve", []):
            f = fs_map.get(title)
            if f and f.status == "resolved":
                issues.append(Issue(
                    type="foreshadow", severity="error",
                    description=f"伏笔'{title}'已回收，不能再次回收",
                    location=f"scene_{sc.get('scene_number', '?')}",
                    fix_instruction=f"移除对伏笔'{title}'的回收",
                ))

    for f in all_fs:
        if (f.status == "planted" and f.target_resolve_chapter
                and f.target_resolve_chapter + 10 < chapter_number):
            issues.append(Issue(
                type="foreshadow", severity="warning",
                description=f"伏笔'{f.title}'严重逾期（目标第{f.target_resolve_chapter}章）",
            ))
    return issues




def run_consistency_check(chapter_number: int, chapter_text: str, scene_contracts: list,
                          session, llm_client) -> ConsistencyReport:
    """Run all consistency checks, return report."""
    report = ConsistencyReport(chapter=chapter_number)

    all_chars = set()
    for sc in scene_contracts:
        all_chars.update(sc.get("characters", []))

    # Deterministic checks
    report.issues.extend(check_contract(chapter_text, scene_contracts, session))
    report.issues.extend(check_timeline(chapter_text, scene_contracts))
    report.issues.extend(check_location(chapter_text, list(all_chars), session))
    report.issues.extend(check_foreshadow(scene_contracts, session, chapter_number))

    # Single LLM call: contract semantic + fact anchors + POV knowledge
    report.issues.extend(check_semantic(chapter_text, scene_contracts, session, llm_client))

    errors = [i for i in report.issues if i.severity == "error"]
    warnings = [i for i in report.issues if i.severity == "warning"]
    logger.info(f"Consistency check: {len(errors)} errors, {len(warnings)} warnings")
    return report
