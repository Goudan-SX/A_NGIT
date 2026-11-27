"""Guardian-AI 核心：AC 自动机关键词、五维加权评分、分省案例。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import ahocorasick
except ImportError:  # pragma: no cover - 依赖缺失时退化为逐条匹配
    ahocorasick = None

from . import db
from .text_normalize import compact_text

ROOT = Path(__file__).resolve().parent.parent.parent
KEYWORDS_JSON = ROOT / "backend" / "data" / "guardian_keywords.json"
CASES_JSON = ROOT / "backend" / "data" / "guardian_cases.json"

LEVELS = {
    "low": ("低风险", "暂未发现明显风险，保持警惕"),
    "medium": ("中风险", "存在可疑信号，建议核实"),
    "high": ("高风险", "建议立即停止沟通"),
    "critical": ("极高风险", "建议立即止损并报警"),
}

URGENCY_SIGNALS = {
    "urgency", "authority_pressure", "isolation", "threat_expose",
    "high_return", "limited_quota", "account_frozen", "fake_police",
    # 直接索要钱财属于施压型行为，纳入“紧迫语气”分量
    "transfer",
}
INFO_SIGNALS = {
    "verification_code", "password", "screen_share", "id_bank_photo",
    "face_auth", "personal_collect",
}


def ensure_data() -> None:
    """新环境启动时从 JSON 导入关键词与案例。"""
    if db.query_one("SELECT COUNT_BIG(*) AS total FROM dbo.guardian_keywords")["total"] == 0:
        if KEYWORDS_JSON.exists():
            for item in json.loads(KEYWORDS_JSON.read_text(encoding="utf-8")):
                db.execute(
                    "INSERT INTO dbo.guardian_keywords (keyword, category, weight, source) VALUES (?, ?, ?, ?)",
                    [item["keyword"], item["category"], item["weight"], item.get("source")],
                )
    if db.query_one("SELECT COUNT_BIG(*) AS total FROM dbo.guardian_cases")["total"] == 0:
        if CASES_JSON.exists():
            for item in json.loads(CASES_JSON.read_text(encoding="utf-8")):
                db.execute(
                    """
                    INSERT INTO dbo.guardian_cases
                        (code, province, region, age_group, category, subtype, scam_type,
                         channel, method, keywords, loss, source, tips)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [item.get("code"), item.get("province"), item.get("region"),
                     item.get("age_group"), item.get("category"), item.get("subtype"),
                     item.get("scam_type"), item.get("channel"), item.get("method"),
                     item.get("keywords"), item.get("loss"), item.get("source"), item.get("tips")],
                )


@lru_cache(maxsize=1)
def _automaton():
    rows = db.query_all("SELECT keyword, category, weight FROM dbo.guardian_keywords WHERE is_active = 1")
    if not rows and KEYWORDS_JSON.exists():
        rows = json.loads(KEYWORDS_JSON.read_text(encoding="utf-8"))
    if ahocorasick is None:
        return None
    automation = ahocorasick.Automaton()
    for row in rows:
        keyword = compact_text(row["keyword"])
        if len(keyword) < 2:
            continue
        automation.add_word(keyword, (keyword, row["category"], int(row["weight"])))
    if len(automation) == 0:
        return None
    automation.make_automaton()
    return automation


def scan_keywords(text: str) -> list[dict[str, Any]]:
    automation = _automaton()
    compact = compact_text(text)
    if not automation or not compact:
        return []
    found: dict[str, dict[str, Any]] = {}
    for _, (keyword, category, weight) in automation.iter(compact):
        if keyword not in found:
            found[keyword] = {"keyword": keyword, "category": category, "weight": weight, "count": 0}
        found[keyword]["count"] += 1
    return sorted(found.values(), key=lambda item: (item["weight"], len(item["keyword"])), reverse=True)


def _signal_score(result: dict[str, Any], ids: set[str], cap: int) -> int:
    total = 0
    for signal in result.get("signals", []):
        if signal.get("protective"):
            continue
        if signal.get("id") in ids:
            total += float(signal.get("weight", 0))
    return min(cap, int(round(total)))


def _level(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def compute(text: str, result: dict[str, Any], semantic_similarity: float = 0.0) -> dict[str, Any]:
    hits = scan_keywords(text)
    keyword_score = min(30, sum(item["weight"] for item in hits))
    urgency_score = _signal_score(result, URGENCY_SIGNALS, 25)
    info_signal_score = _signal_score(result, INFO_SIGNALS, 20)
    pii_score = min(20, int(round(float(result.get("pii_score", 0)) / 25 * 20)))
    pii_component = max(info_signal_score, pii_score)
    link_score = min(15, int(round(max([item.get("risk", 0) for item in result.get("links", [])] or [0]) * 0.15)))
    semantic_score = max(0, min(10, int(round(semantic_similarity * 10))))
    total = keyword_score + urgency_score + pii_component + link_score + semantic_score
    total = max(0, min(100, total))
    level = _level(total)
    label, hint = LEVELS[level]

    result["guardian"] = {
        "score": total,
        "level": level,
        "label": label,
        "components": [
            {"key": "keyword", "name": "敏感词", "score": keyword_score, "max": 30, "desc": "Guardian-AI 关键词库命中"},
            {"key": "urgency", "name": "紧迫语气", "score": urgency_score, "max": 25, "desc": "制造紧迫、恐吓或权威施压"},
            {"key": "pii", "name": "个人信息索取", "score": pii_component, "max": 20, "desc": "验证码、密码、证件、屏幕共享"},
            {"key": "link", "name": "链接可疑度", "score": link_score, "max": 15, "desc": "短链、IP、高风险后缀或敏感路径"},
            {"key": "semantic", "name": "语义相似度", "score": semantic_score, "max": 10, "desc": "与案例库历史案例的相似程度"},
        ],
        "keyword_hits": hits[:20],
    }
    result["risk_score"] = total
    result["risk_level"] = level
    result["risk_label"] = label
    result["risk_hint"] = hint
    if result.get("summary"):
        result["summary"] = re.sub(r"综合风险\s*\d+%", f"综合风险 {total}%", result["summary"])
    merged = list(result.get("matched_keywords", []))
    for item in hits:
        if item["keyword"] not in merged:
            merged.append(item["keyword"])
    result["matched_keywords"] = merged[:16]
    return result


def is_decisive(result: dict[str, Any]) -> bool:
    """高置信/明显低风险跳过 AI；其余模糊文本才交给大模型精判。"""
    guardian = result.get("guardian") or {}
    score = int(guardian.get("score", 0))
    components = {item["key"]: item["score"] for item in guardian.get("components", [])}
    keyword = components.get("keyword", 0)
    pii = components.get("pii", 0)
    link = components.get("link", 0)
    if score >= 80 and (keyword >= 20 or pii >= 15 or link >= 10):
        return True
    if score < 20 and keyword == 0 and pii == 0 and link == 0:
        return True
    return False


def list_provinces() -> list[dict[str, Any]]:
    return db.query_all(
        "SELECT province, COUNT_BIG(*) AS count FROM dbo.guardian_cases GROUP BY province ORDER BY count DESC"
    )


def list_cases(province: str = "", category: str = "", limit: int = 20) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: list[Any] = []
    if province:
        where.append("province = ?")
        params.append(province)
    if category:
        where.append("category = ?")
        params.append(category)
    safe_limit = max(1, min(100, int(limit)))
    return db.query_all(
        f"""
        SELECT TOP ({safe_limit}) id, code, province, region, age_group, category, subtype,
               scam_type, channel, method, keywords, loss, source, tips
        FROM dbo.guardian_cases
        WHERE {' AND '.join(where)}
        ORDER BY id
        """,
        params,
    )
