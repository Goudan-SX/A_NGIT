"""训练印度金融欺诈数据集上的 LightGBM 交易风控模型，并提炼规则入库。

用法：
    python backend/ml/train_transaction_model.py
    python backend/ml/train_transaction_model.py --data-dir backend/data/indian_fraud
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.ml.features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    engineer_frame,
    load_tables,
)


def _ratio(mask: pd.Series, target: pd.Series) -> dict[str, Any]:
    subset = target[mask]
    if len(subset) == 0:
        return {"support": 0.0, "fraud_rate": 0.0, "lift": 0.0}
    base = float(target.mean())
    rate = float(subset.mean())
    return {
        "support": round(len(subset) / len(target), 4),
        "fraud_rate": round(rate, 4),
        "lift": round(rate / base, 2) if base else 0.0,
    }


def build_rules(frame: pd.DataFrame, target: pd.Series) -> list[dict[str, Any]]:
    amount = pd.to_numeric(frame["Transaction_Amount"], errors="coerce").fillna(0)
    credit = pd.to_numeric(frame["Credit_Limit"], errors="coerce").fillna(1).clip(lower=1)
    high_amount = float(amount.quantile(0.95))
    median_amount = float(amount.median())
    conditions = [
        ("CARD_STATUS_NONACTIVE", "失效/挂失/冻结卡交易",
         "卡片状态为 Blocked / Expired / Lost 仍发生交易",
         {"field": "Card_Status", "op": "not_in", "value": ["Active"]}, 40),
        ("AMOUNT_OVER_LIMIT", "交易金额超过信用额度",
         "单笔交易金额超过卡片信用额度，疑似超额盗刷",
         {"field": "AmountToLimit", "op": "gte", "value": 1.0}, 30),
        ("AUTH_FAILED", "多次失败/拒绝授权",
         "交易状态为 Failed / Declined，疑似撞库或连续试探",
         {"field": "Transaction_Status", "op": "in", "value": ["Failed", "Declined"]}, 25),
        ("INTERNATIONAL", "跨境/国际交易",
         "跨境交易且金额异常，需二次核验",
         {"field": "Is_International", "op": "eq", "value": 1}, 15),
        ("HIGH_AMOUNT", "大额交易",
         f"交易金额超过数据集中 95% 分位（{high_amount:.2f}）",
         {"field": "Transaction_Amount", "op": "gte", "value": round(high_amount, 2)}, 12),
        ("HIGH_RISK_MERCHANT", "高风险商户大额交易",
         "高风险商户且金额高于中位数，疑似商户侧欺诈",
         {"all": [
             {"field": "Merchant_Risk_Level", "op": "eq", "value": "High"},
             {"field": "Transaction_Amount", "op": "gte", "value": round(median_amount, 2)},
         ]}, 8),
        ("NIGHT_GEO_MISMATCH", "深夜异地异常",
         "凌晨 0-6 点且客户与商户所在地不一致",
         {"all": [
             {"field": "IsNight", "op": "eq", "value": 1},
             {"field": "StateMismatch", "op": "eq", "value": 1},
         ]}, 4),
    ]
    rules = []
    for code, name, description, condition, weight in conditions:
        mask = evaluate_condition(frame, condition)
        stats = _ratio(mask, target)
        rules.append({
            "code": code,
            "name": name,
            "description": description,
            "condition_json": json.dumps(condition, ensure_ascii=False),
            "risk_weight": weight,
            "support": stats["support"],
            "fraud_rate": stats["fraud_rate"],
            "lift": stats["lift"],
        })
    return rules


def evaluate_condition(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    if "all" in condition:
        mask = pd.Series(True, index=frame.index)
        for child in condition["all"]:
            mask &= evaluate_condition(frame, child)
        return mask
    field = condition.get("field")
    op = condition.get("op", "eq")
    expected = condition.get("value")
    if field == "AmountToLimit":
        amount = pd.to_numeric(frame["Transaction_Amount"], errors="coerce").fillna(0)
        credit = pd.to_numeric(frame["Credit_Limit"], errors="coerce").fillna(1).clip(lower=1)
        series = amount / credit
    elif field == "IsNight":
        hours = pd.to_datetime(frame["Transaction_Time"], format="%H:%M:%S", errors="coerce").dt.hour
        series = (hours < 6).astype(int)
    elif field == "StateMismatch":
        series = (
            frame["Customer_State"].astype(str) != frame["Merchant_State"].astype(str)
        ).astype(int)
    else:
        series = frame.get(field)
        if series is None:
            return pd.Series(False, index=frame.index)
    if op == "in":
        return series.astype(str).isin([str(item) for item in expected])
    if op == "not_in":
        return ~series.astype(str).isin([str(item) for item in expected])
    if op == "eq":
        return series.astype(str) == str(expected)
    if op == "neq":
        return series.astype(str) != str(expected)
    numeric = pd.to_numeric(series, errors="coerce")
    expected_num = float(expected)
    if op == "gt":
        return numeric > expected_num
    if op == "gte":
        return numeric >= expected_num
    if op == "lt":
        return numeric < expected_num
    if op == "lte":
        return numeric <= expected_num
    return pd.Series(False, index=frame.index)


def save_rules(rules: list[dict[str, Any]]) -> None:
    db.ensure_database()
    for rule in rules:
        db.execute(
            """
            MERGE dbo.transaction_rules AS target
            USING (SELECT ? AS code) AS source
            ON target.code = source.code
            WHEN MATCHED THEN
                UPDATE SET name = ?, description = ?, condition_json = ?,
                           risk_weight = ?, support = ?, fraud_rate = ?, lift = ?,
                           source = ?, updated_at = SYSDATETIME(), is_active = 1
            WHEN NOT MATCHED THEN
                INSERT (code, name, description, condition_json, risk_weight,
                        support, fraud_rate, lift, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                rule["code"],
                rule["name"],
                rule["description"],
                rule["condition_json"],
                rule["risk_weight"],
                rule["support"],
                rule["fraud_rate"],
                rule["lift"],
                "indian_financial_fraud",
                rule["code"],
                rule["name"],
                rule["description"],
                rule["condition_json"],
                rule["risk_weight"],
                rule["support"],
                rule["fraud_rate"],
                rule["lift"],
                "indian_financial_fraud",
            ],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "backend" / "data" / "indian_fraud"))
    parser.add_argument("--output-dir", default=str(ROOT / "backend" / "models"))
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] 加载并合并四张表…")
    frame = load_tables(str(data_dir))
    target = pd.to_numeric(frame["Fraud_Flag"], errors="coerce").fillna(0).astype(int)
    print(f"      行数={len(frame)}，欺诈={int(target.sum())}，比例={target.mean():.4%}")

    print("[2/5] 特征工程…")
    X = engineer_frame(frame)
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, target, test_size=0.3, random_state=42, stratify=target
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
    )
    print(f"      训练/验证/测试 = {len(X_train)}/{len(X_val)}/{len(X_test)}")

    print("[3/5] 训练 LightGBM…")
    numeric_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", max_categories=50)),
    ])
    preprocessor = ColumnTransformer([
        ("num", numeric_pipe, NUMERIC_FEATURES),
        ("cat", categorical_pipe, CATEGORICAL_FEATURES),
    ])
    positive = int(y_train.sum())
    negative = len(y_train) - positive
    model = LGBMClassifier(
        n_estimators=350,
        learning_rate=0.05,
        num_leaves=63,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        scale_pos_weight=max(1.0, negative / max(positive, 1)),
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    pipeline = Pipeline([("prep", preprocessor), ("model", model)])
    pipeline.fit(X_train, y_train)

    val_prob = pipeline.predict_proba(X_val)[:, 1]
    precision, recall, thresholds = precision_recall_curve(y_val, val_prob)
    f1_values = (2 * precision * recall) / np.clip(precision + recall, 1e-9, None)
    best_index = int(np.argmax(f1_values[:-1]))
    best_threshold = float(thresholds[best_index]) if len(thresholds) else 0.5
    test_prob = pipeline.predict_proba(X_test)[:, 1]
    y_pred = (test_prob >= best_threshold).astype(int)
    metrics = {
        "auc_roc": round(float(roc_auc_score(y_test, test_prob)), 4),
        "auc_pr": round(float(average_precision_score(y_test, test_prob)), 4),
        "threshold": round(best_threshold, 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
    }
    print("      指标:", metrics)

    print("[4/5] 保存模型与元数据…")
    model_path = output_dir / "transaction_pipeline.joblib"
    joblib.dump(pipeline, model_path)
    feature_names = list(preprocessor.get_feature_names_out())
    importances = getattr(model, "feature_importances_", np.zeros(len(feature_names)))
    top_features = [
        {"feature": name, "importance": int(value)}
        for name, value in sorted(zip(feature_names, importances), key=lambda item: item[1], reverse=True)[:20]
    ]
    metadata = {
        "model_name": "Guardian-AI-Transaction",
        "trained_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "rows": len(frame),
        "fraud_rows": int(target.sum()),
        "metrics": metrics,
        "features": FEATURE_COLUMNS,
        "top_features": top_features,
        "artifact": str(model_path.relative_to(ROOT)).replace("\\", "/"),
    }
    (output_dir / "transaction_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[5/5] 提炼规则并写入 SQL Server…")
    rules = build_rules(frame, target)
    (output_dir / "transaction_rules.json").write_text(
        json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_rules(rules)
    db.execute(
        """
        INSERT INTO dbo.transaction_models
            (model_name, rows_count, fraud_count, auc_roc, auc_pr, threshold,
             artifact_path, metrics_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            metadata["model_name"],
            len(frame),
            int(target.sum()),
            metrics["auc_roc"],
            metrics["auc_pr"],
            metrics["threshold"],
            str(model_path),
            json.dumps(metadata, ensure_ascii=False),
        ],
    )
    print(f"完成：模型 {model_path}")
    print(f"完成：规则 {len(rules)} 条，已写入 transaction_rules")


if __name__ == "__main__":
    main()
