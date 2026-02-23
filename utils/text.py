"""Text processing utilities."""
import re
import json


def extract_json(text: str) -> dict:
    """Extract JSON object from LLM response text."""
    start = text.find('{')
    end = text.rfind('}') + 1
    if start < 0 or end <= start:
        return {}
    json_str = text[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Fix unescaped control characters
        fixed = re.sub(r'[\x00-\x1f]', lambda m: '\\n' if m.group() == '\n' else '', json_str)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json
                return json.loads(repair_json(json_str))
            except Exception:
                return {}


def count_tokens_approx(text: str) -> int:
    """Approximate token count: ~1.5 chars per token for Chinese text."""
    return int(len(text) / 1.5)
