"""临时对话库：按对方 id 隔离保存，1 天 TTL。

需求约定：对方所有聊天数据都入临时库（无分数门槛），按行去重合并保留
完整历史，供 AI 阅读累积上下文并实时更新风险值。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .analyzer import extract_suspicious_snippets

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conversations.db"
TTL_DAYS = 1


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            contact_id TEXT PRIMARY KEY,
            contact_name TEXT NOT NULL,
            window_title TEXT,
            text TEXT,
            risk_score INTEGER DEFAULT 0,
            risk_level TEXT,
            risk_label TEXT,
            summary TEXT,
            result_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            expires_at TEXT
        )
        """
    )
    conn.commit()


def _merge_texts(old: str, new: str) -> str:
    """按行去重合并，保留对方所有历史消息（窗口滚动后旧消息不丢失）。"""
    if not old or not new:
        return new or old
    old_lines = [line for line in old.splitlines() if line.strip()]
    new_lines = [line for line in new.splitlines() if line.strip()]
    if not old_lines:
        return new
    seen = set(old_lines)
    merged = list(old_lines)
    for line in new_lines:
        if line not in seen:
            merged.append(line)
            seen.add(line)
    return "\n".join(merged)


def get_full_text(contact_id: str) -> str:
    """返回某联系人的完整累积文本（供 AI 阅读上下文，不脱敏、不过滤）。"""
    with _connect() as conn:
        _init(conn)
        row = conn.execute("SELECT text FROM conversations WHERE contact_id = ?", [contact_id]).fetchone()
        return str(row["text"] or "") if row else ""


def cleanup() -> None:
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with _connect() as conn:
        _init(conn)
        conn.execute("DELETE FROM conversations WHERE expires_at < ?", [now])


def save(*, contact_id: str, contact_name: str, window_title: str, text: str,
         result: dict[str, Any]) -> bool:
    """保存对方聊天数据；同一联系人按行去重合并，保留全部历史消息。

    需求：对方所有聊天数据都入临时库（无分数门槛），累积上下文供 AI 阅读。
    text 做增量合并，result/score 以最新 AI 确认值为准（UPSERT 覆盖）。
    """
    if not text.strip():
        return False
    score = int(result.get("risk_score", 0))
    now = datetime.now()
    with _connect() as conn:
        _init(conn)
        row = conn.execute("SELECT text FROM conversations WHERE contact_id = ?", [contact_id]).fetchone()
        merged = _merge_texts(str(row["text"] or "") if row else "", text)
        conn.execute(
            """
            INSERT INTO conversations
                (contact_id, contact_name, window_title, text, risk_score, risk_level,
                 risk_label, summary, result_json, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contact_id) DO UPDATE SET
                contact_name=excluded.contact_name,
                window_title=excluded.window_title,
                text=excluded.text,
                risk_score=excluded.risk_score,
                risk_level=excluded.risk_level,
                risk_label=excluded.risk_label,
                summary=excluded.summary,
                result_json=excluded.result_json,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at
            """,
            [
                contact_id, contact_name, window_title, merged, score,
                result.get("risk_level"), result.get("risk_label"),
                str(result.get("summary", ""))[:1000],
                json.dumps(result, ensure_ascii=False),
                now.isoformat(sep=" ", timespec="seconds"),
                now.isoformat(sep=" ", timespec="seconds"),
                (now + timedelta(days=TTL_DAYS)).isoformat(sep=" ", timespec="seconds"),
            ],
        )
        conn.commit()
    return True


def list_contacts() -> list[dict[str, Any]]:
    cleanup()
    with _connect() as conn:
        _init(conn)
        rows = conn.execute(
            """
            SELECT contact_id, contact_name, risk_score, risk_level, risk_label,
                   summary, updated_at, expires_at
            FROM conversations ORDER BY risk_score DESC, updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get(contact_id: str) -> dict[str, Any] | None:
    cleanup()
    with _connect() as conn:
        _init(conn)
        row = conn.execute("SELECT * FROM conversations WHERE contact_id = ?", [contact_id]).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["result"] = json.loads(data.pop("result_json") or "{}")
        except json.JSONDecodeError:
            data["result"] = {}
        # 前端只展示可疑片段，不展示完整原文（隐私保护）
        full_text = data.pop("text", "") or ""
        data["text"] = extract_suspicious_snippets(full_text, data.get("result"))
        return data


def delete(contact_id: str) -> bool:
    with _connect() as conn:
        _init(conn)
        changed = conn.execute("DELETE FROM conversations WHERE contact_id = ?", [contact_id]).rowcount
        conn.commit()
        return bool(changed)
