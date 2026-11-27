"""导入 Guardian-AI 关键词规则与分省案例。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402

SOURCE = ROOT / "backend" / "data" / "guardian_source"
KEYWORD_JSON = ROOT / "backend" / "data" / "guardian_keywords.json"
CASE_JSON = ROOT / "backend" / "data" / "guardian_cases.json"

CATEGORY_WEIGHTS = {
    "话术关键词": 10,
    "高频词": 4,
    "诈骗类型": 12,
    "平台/渠道": 5,
    "话术诱导": 10,
    "受害场景": 3,
    "风险行为": 12,
}

MANUAL_KEYWORDS = [
    ("刷单返利", "话术诱导", 12),
    ("垫付", "风险行为", 10),
    ("验证码", "风险行为", 12),
    ("屏幕共享", "风险行为", 12),
    ("共享屏幕", "风险行为", 12),
    ("安全账户", "话术诱导", 12),
    ("注销校园贷", "诈骗类型", 12),
    ("保证金", "话术诱导", 10),
    ("解冻金", "话术诱导", 10),
    ("征信", "话术诱导", 8),
    ("冒充公检法", "诈骗类型", 12),
    ("下载会议", "风险行为", 10),
    ("远程控制", "风险行为", 12),
    ("扫码", "风险行为", 8),
    ("两卡", "风险行为", 10),
    ("跑分", "风险行为", 12),
    ("手机口", "风险行为", 12),
    ("转我点", "风险行为", 15),
    ("转我", "风险行为", 15),
    ("给我转", "风险行为", 15),
    ("给我卡里打点钱", "风险行为", 20),
    ("卡里打点钱", "风险行为", 20),
    ("打点钱", "风险行为", 15),
    ("打钱", "风险行为", 15),
    ("转钱", "风险行为", 12),
    ("汇款", "风险行为", 10),
    ("收款码", "风险行为", 10),
    ("借钱", "风险行为", 8),
    ("手机快没电", "风险行为", 12),
    ("长话短说", "风险行为", 8),
    ("在医院", "风险行为", 8),
    ("住院费", "风险行为", 10),
    ("微信限额", "风险行为", 10),
    ("转不出去", "风险行为", 10),
    ("帮我垫", "风险行为", 15),
    ("明天一早还你", "风险行为", 12),
    ("账号我发你", "风险行为", 12),
]

PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
]


def clean_keyword(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("“”")
    return re.sub(r"\s+", "", text)


def build_keywords() -> list[dict]:
    items: dict[str, dict] = {}
    for filename in ["keywords_v2.csv", "keywords_v1.csv"]:
        path = SOURCE / filename
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        for _, row in frame.iterrows():
            category = str(row.get("类别", "")).strip()
            keyword = clean_keyword(row.get("关键词", row.get("关键词/短语", "")))
            if not keyword or len(keyword) < 2 or len(keyword) > 60:
                continue
            weight = CATEGORY_WEIGHTS.get(category, 6)
            # 高频词里过滤过于泛化的词
            if category == "高频词" and (len(keyword) < 3 or keyword in {"其中", "收到", "看到", "对方以", "为由", "笔共", "万余元"}):
                continue
            if keyword not in items or weight > items[keyword]["weight"]:
                items[keyword] = {
                    "keyword": keyword,
                    "category": category or "其他",
                    "weight": weight,
                    "source": filename,
                }
    for keyword, category, weight in MANUAL_KEYWORDS:
        if keyword not in items or weight > items[keyword]["weight"]:
            items[keyword] = {"keyword": keyword, "category": category, "weight": weight, "source": "manual"}
    return sorted(items.values(), key=lambda item: item["weight"], reverse=True)


def province_of(value: str) -> str:
    text = str(value or "")
    for province in PROVINCES:
        if province in text:
            return province
    return "其他"


def build_cases() -> list[dict]:
    path = SOURCE / "cases.csv"
    frame = pd.read_csv(path).fillna("")
    cases = []
    for _, row in frame.iterrows():
        code = str(row.get("编号", "")).strip()
        if not code:
            continue
        cases.append({
            "code": code,
            "province": province_of(row.get("地区", "")),
            "region": str(row.get("地区", ""))[:80],
            "age_group": str(row.get("受害人年龄段", ""))[:40],
            "category": str(row.get("一级类型", ""))[:80],
            "subtype": str(row.get("细分类型", ""))[:120],
            "scam_type": str(row.get("诈骗类型", ""))[:120],
            "channel": str(row.get("接触渠道", ""))[:120],
            "method": str(row.get("作案手法", "")),
            "keywords": str(row.get("话术/关键词", ""))[:500],
            "loss": str(row.get("损失情况（元）", ""))[:100],
            "source": str(row.get("来源", ""))[:300],
            "tips": str(row.get("防范提示", ""))[:1000],
        })
    return cases


def save_json(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_db(keywords: list[dict], cases: list[dict]) -> None:
    db.ensure_database()
    for item in keywords:
        db.execute(
            """
            MERGE dbo.guardian_keywords AS target
            USING (SELECT ? AS keyword) AS source
            ON target.keyword = source.keyword
            WHEN MATCHED THEN
                UPDATE SET category = ?, weight = ?, source = ?, is_active = 1
            WHEN NOT MATCHED THEN
                INSERT (keyword, category, weight, source)
                VALUES (?, ?, ?, ?);
            """,
            [
                item["keyword"], item["category"], item["weight"], item["source"],
                item["keyword"], item["category"], item["weight"], item["source"],
            ],
        )
    for item in cases:
        db.execute(
            """
            MERGE dbo.guardian_cases AS target
            USING (SELECT ? AS code) AS source
            ON target.code = source.code
            WHEN MATCHED THEN
                UPDATE SET province = ?, region = ?, age_group = ?, category = ?,
                             subtype = ?, scam_type = ?, channel = ?, method = ?,
                             keywords = ?, loss = ?, source = ?, tips = ?
            WHEN NOT MATCHED THEN
                INSERT (code, province, region, age_group, category, subtype,
                        scam_type, channel, method, keywords, loss, source, tips)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                item["code"], item["province"], item["region"], item["age_group"],
                item["category"], item["subtype"], item["scam_type"], item["channel"],
                item["method"], item["keywords"], item["loss"], item["source"], item["tips"],
                item["code"], item["province"], item["region"], item["age_group"],
                item["category"], item["subtype"], item["scam_type"], item["channel"],
                item["method"], item["keywords"], item["loss"], item["source"], item["tips"],
            ],
        )


def main() -> None:
    keywords = build_keywords()
    cases = build_cases()
    save_json(KEYWORD_JSON, keywords)
    save_json(CASE_JSON, cases)
    save_db(keywords, cases)
    print(f"关键词 {len(keywords)} 条，案例 {len(cases)} 条")
    print(f"案例省份：{sorted(set(item['province'] for item in cases))}")


if __name__ == "__main__":
    main()
