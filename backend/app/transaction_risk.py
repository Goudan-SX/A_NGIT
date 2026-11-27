"""交易风控推理：LightGBM 概率 + 数据集提炼规则。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from . import db
from ..ml.features import engineer_frame, raw_input_to_frame

ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = ROOT / "backend" / "models" / "transaction_pipeline.joblib"
METADATA_PATH = ROOT / "backend" / "models" / "transaction_metadata.json"


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        return None
    try:
        return joblib.load(MODEL_PATH)
    except Exception:  # noqa: BLE001 - 版本不匹配时允许规则引擎兜底
        return None


def load_metadata() -> dict[str, Any]:
    if not METADATA_PATH.exists():
        return {}
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _evaluate_condition(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
    if "all" in condition:
        return all(_evaluate_condition(payload, child) for child in condition["all"])
    if "any" in condition:
        return any(_evaluate_condition(payload, child) for child in condition["any"])
    field = condition.get("field")
    op = condition.get("op", "eq")
    expected = condition.get("value")
    if field == "AmountToLimit":
        amount = float(payload.get("Transaction_Amount", payload.get("amount", 0)) or 0)
        credit = max(1.0, float(payload.get("Credit_Limit", payload.get("credit_limit", 1)) or 1))
        actual = amount / credit
    elif field == "IsNight":
        time_text = str(payload.get("Transaction_Time", payload.get("time", "00:00:00")))
        try:
            actual = 1 if int(time_text.split(":")[0]) < 6 else 0
        except (ValueError, IndexError):
            actual = 0
    elif field == "StateMismatch":
        actual = 1 if str(payload.get("Customer_State", "")) != str(payload.get("Merchant_State", "")) else 0
    else:
        actual = payload.get(field)

    if op == "in":
        return str(actual) in {str(item) for item in expected}
    if op == "not_in":
        return str(actual) not in {str(item) for item in expected}
    if op == "eq":
        return str(actual) == str(expected)
    if op == "neq":
        return str(actual) != str(expected)
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


RULES_PATH = ROOT / "backend" / "models" / "transaction_rules.json"


def ensure_rules() -> int:
    """首次启动时把模型目录中的规则 JSON 导入数据库。"""
    existing = db.query_one("SELECT COUNT_BIG(*) AS total FROM dbo.transaction_rules")
    if existing and int(existing["total"]) > 0:
        return 0
    if not RULES_PATH.exists():
        return 0
    try:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    created = 0
    for rule in rules:
        db.execute(
            """
            INSERT INTO dbo.transaction_rules
                (code, name, description, condition_json, risk_weight,
                 support, fraud_rate, lift, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                rule.get("code"),
                rule.get("name"),
                rule.get("description"),
                rule.get("condition_json") or "{}",
                int(rule.get("risk_weight", 0)),
                rule.get("support"),
                rule.get("fraud_rate"),
                rule.get("lift"),
                "indian_financial_fraud",
            ],
        )
        created += 1
    return created


def list_rules() -> list[dict[str, Any]]:
    rows = db.query_all(
        """
        SELECT code, name, description, condition_json, risk_weight,
               support, fraud_rate, lift
        FROM dbo.transaction_rules WHERE is_active = 1 ORDER BY risk_weight DESC
        """
    )
    result = []
    for row in rows:
        try:
            condition = json.loads(row["condition_json"])
        except json.JSONDecodeError:
            condition = {}
        row["condition"] = condition
        result.append(row)
    return result


def predict(payload: dict[str, Any]) -> dict[str, Any]:
    rules = list_rules()
    matched = []
    rule_score = 0
    for rule in rules:
        if _evaluate_condition(payload, rule.get("condition") or {}):
            matched.append({
                "code": rule["code"],
                "name": rule["name"],
                "description": rule["description"],
                "risk_weight": rule["risk_weight"],
            })
            rule_score += int(rule["risk_weight"])
    rule_score = min(100, rule_score)

    probability = None
    model_available = False
    pipeline = load_model()
    if pipeline is not None:
        try:
            frame = raw_input_to_frame(payload)
            features = engineer_frame(frame)
            model = pipeline.named_steps.get("model") if hasattr(pipeline, "named_steps") else None
            classes = list(getattr(model, "classes_", [0, 1]))
            positive_col = classes.index(1) if 1 in classes else 1
            probability = float(pipeline.predict_proba(features)[0][positive_col])
            model_available = True
        except Exception:  # noqa: BLE001
            probability = None

    metadata = load_metadata()
    threshold = float((metadata.get("metrics") or {}).get("threshold") or 0.5)
    model_score = int(round((probability or 0) * 100))
    threshold_hit = bool(probability is not None and probability >= threshold)
    score = max(rule_score, model_score)
    if score >= 80:
        level, label, hint = "critical", "极高风险", "建议拒绝交易并人工复核"
    elif score >= 60:
        level, label, hint = "high", "高风险", "建议拦截并要求二次验证"
    elif score >= 30:
        level, label, hint = "medium", "中风险", "建议加强验证"
    else:
        level, label, hint = "low", "低风险", "可正常放行，保持监控"

    return {
        "model_available": model_available,
        "fraud_probability": round(probability, 4) if probability is not None else None,
        "fraud_percent": model_score if probability is not None else None,
        "model_threshold_hit": threshold_hit,
        "rule_score": rule_score,
        "risk_score": score,
        "risk_level": level,
        "risk_label": label,
        "risk_hint": hint,
        "threshold": threshold,
        "model_name": metadata.get("model_name"),
        "matched_rules": matched,
        "rule_count": len(rules),
        "explanation": ("命中 " + "、".join(item["name"] for item in matched)) if matched else "未命中已提炼的高风险规则",
    }


def model_info() -> dict[str, Any]:
    metadata = load_metadata()
    return {
        "available": load_model() is not None,
        "metadata": metadata,
        "rule_count": db.query_one(
            "SELECT COUNT_BIG(*) AS total FROM dbo.transaction_rules WHERE is_active = 1"
        )["total"],
    }