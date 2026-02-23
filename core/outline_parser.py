"""Outline parser for 细纲 markdown files."""
import re


def parse_outline(outline_file: str, chapter_number: int) -> dict:
    """Parse outline file and extract info for the given chapter number."""
    with open(outline_file, "r", encoding="utf-8") as f:
        text = f.read()

    # Split into chapters by ## heading
    chapters = re.split(r'(?=^## )', text, flags=re.MULTILINE)
    
    for chunk in chapters:
        # Match chapter number in heading
        m = re.match(r'## 第(\d+)章[：:]\s*(.+)', chunk.strip())
        if not m:
            continue
        if int(m.group(1)) != chapter_number:
            continue
        
        title = m.group(2).strip()
        body = chunk[m.end():].strip()
        
        return {
            "title": title,
            "characters": _extract_list_field(body, r'出场[人角][物色]'),
            "events": _extract_numbered_list(body, r'核心事件'),
            "opening": _extract_text_field(body, r'开头'),
            "middle": _extract_text_field(body, r'中间'),
            "ending": _extract_text_field(body, r'结尾'),
            "foreshadows": _extract_text_field(body, r'伏笔'),
            "forbidden": _extract_numbered_list(body, r'禁止事项') or _extract_list_field(body, r'禁止事项'),
            "word_count": _extract_word_count(body),
            "_raw_text": body,
        }
    
    raise ValueError(f"Chapter {chapter_number} not found in {outline_file}")


def _extract_text_field(body: str, label_pattern: str) -> str:
    """Extract a **label：** value field."""
    m = re.search(
        rf'\*\*{label_pattern}[：:]\*\*\s*(.+?)(?=\n\*\*|\n## |\Z)',
        body, re.DOTALL
    )
    return m.group(1).strip() if m else ""


def _extract_list_field(body: str, label_pattern: str) -> list:
    """Extract a comma-separated list field."""
    text = _extract_text_field(body, label_pattern)
    if not text:
        return []
    # Split by Chinese/English comma, 、
    return [s.strip() for s in re.split(r'[,，、]', text) if s.strip()]


def _extract_numbered_list(body: str, label_pattern: str) -> list:
    """Extract a numbered list under a label."""
    m = re.search(
        rf'\*\*{label_pattern}[：:]\*\*\s*\n((?:\d+\..+\n?)+)',
        body
    )
    if not m:
        return []
    items = re.findall(r'\d+\.\s*(.+)', m.group(1))
    return [item.strip() for item in items]


def _extract_word_count(body: str) -> int:
    """Extract target word count."""
    m = re.search(r'(\d{3,5})\s*[-~到]\s*\d{3,5}\s*字', body)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d{3,5})\s*字', body)
    return int(m.group(1)) if m else 2500
