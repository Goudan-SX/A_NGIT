"""数据库案例优先匹配 + 相似度计算。

流程：
1. 每次文本检测先归一化并计算哈希；
2. 命中已有案例时直接复用案例结果，再交给 AI 二次复核；
3. 未命中时走 AI / 规则分析。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import analyzer, db

SIMILARITY_THRESHOLD = 0.74

SEED_CASES = [
    {
        "title": "刷单返利 + 屏幕共享复合诈骗",
        "category": "刷单返利",
        "content": "[11:42] 陌生好友：亲，动动手指日赚 300，刷单返利，先垫付后返还。\n"
                   "[11:43] 陌生好友：你的账户被冻结了，把验证码发给我就能解冻。\n"
                   "[11:44] 陌生好友：下载会议 App 并开启屏幕共享，我远程指导你操作。",
    },
    {
        "title": "冒充客服理赔套取证件与验证码",
        "category": "冒充客服退款",
        "content": "【客服】您的订单理赔已通过，请提供身份证 110101199003071234、"
                   "手机号 13800138000、银行卡 6222021234567890123，并把短信验证码 123456 发给我。",
    },
    {
        "title": "冒充公检法要求转入安全账户",
        "category": "冒充公检法",
        "content": "我是公安局办案民警，你的银行卡涉嫌洗钱，现在需要配合调查。"
                   "不要告诉家人，保持通话，把资金转到安全账户接受审查，否则马上冻结账户。",
    },
    {
        "title": "虚假投资理财导师带单",
        "category": "虚假投资理财",
        "content": "导师带你做内部投资，稳赚不赔，先小额充值试试，收益马上到账。"
                   "现在下载我们的投资 App，充值越多返利越高，提现需要先交保证金。",
    },
    {
        "title": "网络贷款先收解冻费",
        "category": "网络贷款",
        "content": "你的贷款额度已审批，放款前需要先交 2000 元解冻费和认证费，"
                   "刷流水包装征信后马上放款，逾期会影响征信。",
    },
    {
        "title": "游戏账号低价充值私下交易",
        "category": "游戏账号交易",
        "content": "低价充值游戏点券，加 QQ 私聊，先付保证金，客服解冻后马上到账，"
                   "不要走官方平台，私下转账更便宜。",
    },
    {
        "title": "正常班会通知（低风险样本）",
        "category": "正常内容",
        "content": "同学你好，明天下午 3 点在教学楼 302 开班会，请带好学生证，收到请回复。",
    },
]


def normalize(text: str) -> str:
    value = (text or "").lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]<>《》]", "", value)
    return value


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _bigrams(text: str) -> set[str]:
    if len(text) <= 1:
        return {text} if text else set()
    return {text[index:index + 2] for index in range(len(text) - 1)}


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    a = _bigrams(left)
    b = _bigrams(right)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    jaccard = intersection / union
    containment = intersection / min(len(a), len(b))
    length_ratio = min(len(left), len(right)) / max(len(left), len(right))
    # 长文本包含短文本时给一定加权，但避免短句误命中长案例
    score = max(jaccard, containment * min(1.0, length_ratio * 1.25))
    return round(score, 4)


def seed_cases() -> int:
    """首次启动写入内置案例；已存在相同内容则跳过。"""
    created = 0
    for item in SEED_CASES:
        content = item["content"]
        norm = normalize(content)
        digest = content_hash(content)
        exists = db.query_one("SELECT id FROM dbo.scam_cases WHERE content_hash = ?", [digest])
        if exists:
            continue
        result = analyzer.analyze_text(content)
        db.execute(
            """
            INSERT INTO dbo.scam_cases
                (title, category, content, content_norm, content_hash, risk_score,
                 risk_level, scam_type, summary, result_json, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                item["title"],
                item["category"],
                content,
                norm,
                digest,
                int(result.get("risk_score", 0)),
                result.get("risk_level", "low"),
                result.get("scam_type", ""),
                result.get("summary", ""),
                db.json_dumps(result),
                "seed",
            ],
        )
        created += 1
    return created


def _row_to_case(row: dict[str, Any]) -> dict[str, Any]:
    result = {}
    try:
        value = json.loads(row.get("result_json") or "{}")
        if isinstance(value, dict):
            result = value
    except json.JSONDecodeError:
        pass
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "content": row["content"],
        "risk_score": row["risk_score"],
        "risk_level": row["risk_level"],
        "scam_type": row["scam_type"],
        "summary": row["summary"],
        "result": result,
        "hit_count": row.get("hit_count", 0),
    }


def lookup(text: str) -> dict[str, Any]:
    norm = normalize(text)
    if len(norm) < 4:
        return {"hit": False, "nearest": None}
    rows = db.query_all(
        """
        SELECT id, title, category, content, content_norm, content_hash,
               risk_score, risk_level, scam_type, summary, result_json, hit_count
        FROM dbo.scam_cases
        WHERE is_active = 1
        ORDER BY id
        """
    )
    if not rows:
        return {"hit": False, "nearest": None}
    digest = content_hash(text)
    best = None
    best_score = 0.0
    best_exact = False
    for row in rows:
        score = 1.0 if row["content_hash"] == digest else similarity(norm, row["content_norm"])
        if score > best_score:
            best = row
            best_score = score
            best_exact = row["content_hash"] == digest
    if not best:
        return {"hit": False, "nearest": None}
    case = _row_to_case(best)
    if best_score >= SIMILARITY_THRESHOLD:
        db.execute("UPDATE dbo.scam_cases SET hit_count = hit_count + 1 WHERE id = ?", [case["id"]])
        return {
            "hit": True,
            "exact": best_exact,
            "similarity": best_score,
            "case": case,
        }
    return {
        "hit": False,
        "nearest": {
            "case_id": case["id"],
            "title": case["title"],
            "similarity": best_score,
            "threshold": SIMILARITY_THRESHOLD,
        },
    }


def _sanitize_for_store(text: str, result: dict[str, Any]) -> str:
    """入库前替换文本中的 PII，避免案例库保存明文证件号/银行卡。"""
    value = text
    replacements = []
    for item in result.get("pii", []):
        if item.get("source") == "media":
            continue
        for position in item.get("positions", []):
            start = position.get("start")
            end = position.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(value):
                replacements.append((start, end, item.get("value") or "[已脱敏]"))
    for start, end, masked in sorted(replacements, reverse=True):
        value = value[:start] + masked + value[end:]
    return value


def add_case_from_result(text: str, result: dict[str, Any], source: str = "auto") -> bool:
    """把未命中过的检测内容收录为案例；重复内容直接跳过。"""
    if len(normalize(text)) < 8:
        return False
    stored_text = _sanitize_for_store(text, result)
    norm = normalize(stored_text)
    digest = content_hash(stored_text)
    exists = db.query_one("SELECT id FROM dbo.scam_cases WHERE content_hash = ?", [digest])
    if exists:
        return False
    payload = dict(result)
    payload.pop("id", None)
    payload.pop("created_at", None)
    payload.pop("match", None)
    scam_type = str(result.get("scam_type") or "待分类")[:64]
    title = f"自动收录 · {scam_type}"
    db.execute(
        """
        INSERT INTO dbo.scam_cases
            (title, category, content, content_norm, content_hash, risk_score,
             risk_level, scam_type, summary, result_json, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            title,
            scam_type,
            stored_text,
            norm,
            digest,
            int(result.get("risk_score", 0)),
            result.get("risk_level", "low"),
            scam_type,
            str(result.get("summary", ""))[:1000],
            db.json_dumps(payload),
            source,
        ],
    )
    return True


def count_cases() -> int:
    row = db.query_one("SELECT COUNT_BIG(*) AS total FROM dbo.scam_cases WHERE is_active = 1")
    return int(row["total"]) if row else 0


def result_from_case(case: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    """把数据库案例转换成统一的 analysis 结果。"""
    result = dict(case.get("result") or {})
    result["risk_score"] = case["risk_score"]
    result["risk_level"] = case["risk_level"]
    result["risk_label"] = analyzer.LEVELS.get(case["risk_level"], analyzer.LEVELS["low"])["label"]
    result["risk_hint"] = analyzer.LEVELS.get(case["risk_level"], analyzer.LEVELS["low"])["hint"]
    result["scam_type"] = case.get("scam_type") or result.get("scam_type", "")
    result["summary"] = case.get("summary") or result.get("summary", "")
    result["engine"] = {
        "name": "database-match",
        "ai": False,
        "provider": "database",
        "note": f"数据库案例命中：{case['title']}",
    }
    result["match"] = {
        "hit": True,
        "exact": match.get("exact", False),
        "similarity": match.get("similarity", 0),
        "case_id": case["id"],
        "title": case["title"],
        "category": case.get("category"),
        "reviewed_by_ai": False,
        "review_provider": None,
        "review_confidence": None,
        "review_verdict": None,
    }
    result.pop("id", None)
    return result
