from __future__ import annotations

import json


ANALYSIS_FIELDS = ("overview", "insight", "suggestion")


def normalize_analysis(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("AI analysis must be a JSON object")

    analysis: dict[str, object] = {}
    for field in ANALYSIS_FIELDS:
        text = value.get(field)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"AI analysis field {field} is missing")
        analysis[field] = text.strip()

    combined = "".join(str(analysis[field]) for field in ANALYSIS_FIELDS)
    raw_highlights = value.get("highlights", [])
    if not isinstance(raw_highlights, list):
        raw_highlights = []

    highlights: list[str] = []
    for item in raw_highlights:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if not term or len(term) > 12 or term not in combined or term in highlights:
            continue
        highlights.append(term)
        if len(highlights) == 5:
            break
    analysis["highlights"] = highlights
    return analysis


def parse_cached_analysis(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        return normalize_analysis(json.loads(value))
    except (json.JSONDecodeError, ValueError, TypeError):
        return {
            "overview": value.strip(),
            "insight": "历史总结未包含结构化需求洞察。",
            "suggestion": "可重新生成总结以获得完整的客户画像分析。",
            "highlights": [],
        }
