"""临时对话库：按 用户 + 对方 id 隔离保存，1 天 TTL。

统一键名：{user_key}:c:{contact_id}，例如 u1001:root:c:~。
旧版仅按 contact_id 存储的数据在首次连接时自动迁移到 root（u1001:root）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import tenant
from .analyzer import extract_suspicious_snippets

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conversations.db"
TTL_DAYS = 1

_COLUMNS = """
    conversation_key TEXT PRIMARY KEY,
    user_id          INTEGER NOT NULL,
    user_key         TEXT NOT NULL,
    contact_id       TEXT NOT NULL,
    contact_name     TEXT NOT NULL,
    window_title     TEXT,
    text             TEXT,
    risk_score       INTEGER DEFAULT 0,
    risk_level       TEXT,
    risk_label       TEXT,
    summary          TEXT,
    result_json      TEXT,
    created_at       TEXT,
    updated_at       TEXT,
    expires_at       TEXT,
    UNIQUE(user_key, contact_id)
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _create_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS conversations ({_COLUMNS})")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_conversations_user ON conversations(user_id, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_conversations_expire ON conversations(expires_at)")


def _init(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if columns and "user_key" not in columns:
        # 旧版表：只有 contact_id 主键。整体迁移到 root 租户。
        conn.execute("ALTER TABLE conversations RENAME TO conversations_legacy")
        _create_table(conn)
        conn.execute(
            """
            INSERT INTO conversations
                (conversation_key, user_id, user_key, contact_id, contact_name,
                 window_title, text, risk_score, risk_level, risk_label, summary,
                 result_json, created_at, updated_at, expires_at)
            SELECT 'u1001:root:c:' || contact_id, 1001, 'u1001:root', contact_id,
                   contact_name, window_title, text, risk_score, risk_level,
                   risk_label, summary, result_json, created_at, updated_at, expires_at
            FROM conversations_legacy
            """
        )
        conn.execute("DROP TABLE conversations_legacy")
        conn.commit()
    else:
        _create_table(conn)
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


def _now_text() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def get_full_text(contact_id: str) -> str:
    """返回当前用户某联系人的完整累积文本（供 AI 阅读上下文）。"""
    with _connect() as conn:
        _init(conn)
        row = conn.execute(
            "SELECT text FROM conversations WHERE user_id = ? AND contact_id = ?",
            [tenant.user_id(), contact_id],
        ).fetchone()
        return str(row["text"] or "") if row else ""


def cleanup() -> int:
    """清理所有租户的过期对话，返回删除条数。"""
    now = _now_text()
    with _connect() as conn:
        _init(conn)
        changed = conn.execute("DELETE FROM conversations WHERE expires_at < ?", [now]).rowcount
        conn.commit()
        return int(changed or 0)


def save(*, contact_id: str, contact_name: str, window_title: str, text: str,
         result: dict[str, Any]) -> bool:
    """保存对方聊天数据；同一用户+联系人按行去重合并，保留全部历史消息。"""
    if not text.strip():
        return False
    score = int(result.get("risk_score", 0))
    now = datetime.now()
    user_id = tenant.user_id()
    user_key = tenant.user_key()
    key = tenant.make_conversation_key(user_key, contact_id)
    with _connect() as conn:
        _init(conn)
        row = conn.execute(
            "SELECT text FROM conversations WHERE user_id = ? AND contact_id = ?",
            [user_id, contact_id],
        ).fetchone()
        merged = _merge_texts(str(row["text"] or "") if row else "", text)
        conn.execute(
            """
            INSERT INTO conversations
                (conversation_key, user_id, user_key, contact_id, contact_name,
                 window_title, text, risk_score, risk_level, risk_label, summary,
                 result_json, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_key) DO UPDATE SET
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
                key, user_id, user_key, contact_id, contact_name,
                window_title, merged, score,
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
            FROM conversations
            WHERE user_id = ?
            ORDER BY risk_score DESC, updated_at DESC
            """,
            [tenant.user_id()],
        ).fetchall()
        return [dict(row) for row in rows]


def get(contact_id: str) -> dict[str, Any] | None:
    cleanup()
    with _connect() as conn:
        _init(conn)
        row = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ? AND contact_id = ?",
            [tenant.user_id(), contact_id],
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data.pop("conversation_key", None)
        try:
            data["result"] = json.loads(data.pop("result_json") or "{}")
        except json.JSONDecodeError:
            data["result"] = {}
        full_text = data.pop("text", "") or ""
        data["text"] = extract_suspicious_snippets(full_text, data.get("result"))
        return data


def delete(contact_id: str) -> bool:
    with _connect() as conn:
        _init(conn)
        changed = conn.execute(
            "DELETE FROM conversations WHERE user_id = ? AND contact_id = ?",
            [tenant.user_id(), contact_id],
        ).rowcount
        conn.commit()
        return bool(changed)
