"""Stage 2: Scene-by-scene generation using Opus."""
import logging
import time

logger = logging.getLogger(__name__)


def _check_control(should_cancel=None, should_pause=None) -> None:
    from core.interrupts import GenerationCancelled

    while callable(should_pause) and should_pause():
        if callable(should_cancel) and should_cancel():
            raise GenerationCancelled("Job canceled by user")
        time.sleep(0.4)
    if callable(should_cancel) and should_cancel():
        raise GenerationCancelled("Job canceled by user")


def write_scenes(
    scene_contracts: list,
    session,
    llm_client,
    rag_manager,
    style_guide: str,
    config: dict,
    should_cancel=None,
    should_pause=None,
) -> str:
    """Generate all scenes for a chapter, return full chapter text."""
    from core.context_builder import build_scene_prompt, generate_bridge_memo

    scenes = []
    bridge_memo = ""
    accumulated_text = ""

    for i, sc in enumerate(scene_contracts):
        _check_control(should_cancel=should_cancel, should_pause=should_pause)
        scene_num = sc.get("scene_number", i + 1)
        logger.info(f"Generating scene {scene_num}/{len(scene_contracts)}...")

        # #2: POV isolation - clear bridge_memo if POV changed
        if i > 0:
            prev_pov = scene_contracts[i - 1].get("pov_character", "")
            curr_pov = sc.get("pov_character", "")
            if prev_pov and curr_pov and prev_pov != curr_pov:
                logger.info(f"POV changed ({prev_pov} -> {curr_pov}), clearing bridge memo")
                bridge_memo = ""

        # #3: chapter context - last 1500 chars of accumulated text
        chapter_context = accumulated_text[-1500:] if accumulated_text else ""

        prompt = build_scene_prompt(
            scene_contract=sc,
            session=session,
            rag_manager=rag_manager,
            style_guide=style_guide,
            bridge_memo=bridge_memo,
            config=config,
            chapter_context=chapter_context,
        )

        scene_text = llm_client.call_opus(prompt)

        if not scene_text.strip():
            logger.error(f"Scene {scene_num} returned empty content")
            continue

        scenes.append(scene_text.strip())
        accumulated_text += "\n\n" + scene_text.strip()

        # Generate bridge memo for next scene
        if i < len(scene_contracts) - 1:
            _check_control(should_cancel=should_cancel, should_pause=should_pause)
            bridge_memo = generate_bridge_memo(scene_text, llm_client)

    return "\n\n---\n\n".join(scenes)


def targeted_rewrite(chapter_text: str, fix_instruction: str, location: str,
                     llm_client, scene_prompt: str = "") -> str:
    """Rewrite a specific section of the chapter based on fix instruction."""
    parts = []
    if scene_prompt:
        parts.append("【原始写作上下文（供参考，确保修改后仍符合所有约束）】")
        parts.append(scene_prompt[-4000:])
        parts.append("")
    parts.append("请修改以下章节中的问题段落。")
    parts.append("")
    parts.append(f"【问题位置】{location}")
    parts.append(f"【修复指令】{fix_instruction}")
    parts.append("")
    parts.append("【完整章节】")
    parts.append(chapter_text)
    parts.append("")
    parts.append("请输出修改后的完整章节正文。只修改问题段落，其他部分保持不变。")

    return llm_client.call_opus("\n".join(parts))
