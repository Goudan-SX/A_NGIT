"""多模态 AI 公共解析工具：DeepSeek / Qwen 共用的 JSON 提取与证据转换。"""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json(text: str) -> dict[str, Any] | None:
    """从模型回复中提取 JSON，兼容 JSON 代码块与前后说明文字。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith(chr(96) * 3):
        cleaned = re.sub(r"^" + chr(96) * 3 + r"(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*" + chr(96) * 3 + r"$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group())
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def signals_to_evidence(data: dict[str, Any], provider: str = "ai") -> list[dict[str, Any]]:
    """把模型返回的风险点转换成统一证据结构。"""
    dimension_map = {
        "script": "script",
        "financial": "financial",
        "info": "info",
        "channel": "channel",
        "identity": "identity",
    }
    result = []
    for index, item in enumerate(data.get("signals") or []):
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension", "script"))
        weight = item.get("weight", 8)
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            weight = 8
        result.append({
            "id": f"{provider}_{index}",
            "label": str(item.get("label", "语义风险"))[:40],
            "dim": dimension_map.get(dimension, "script"),
            "weight": max(1, min(30, weight)),
            "severity": "high" if weight >= 12 else "medium",
            "count": 1,
            "evidence": str(item.get("evidence", ""))[:600],
            "protective": False,
            "source": provider,
        })
    return result
