"""临时对话库：按对方 id 隔离保存，1 天 TTL。"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conversations.db"
MIN_STORE_SCORE = 40
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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def cleanup() -> None:
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with _connect() as conn:
        _init(conn)
        conn.execute("DELETE FROM conversations WHERE expires_at < ?", [now])


def save(*, contact_id: str, contact_name: str, window_title: str, text: str,
         result: dict[str, Any]) -> bool:
    """只保存可能含诈骗信息的数据；90% 相似以最新文本为准。"""
    score = int(result.get("risk_score", 0))
    if score < MIN_STORE_SCORE or not text.strip():
        return False
    now = datetime.now()
    with _connect() as conn:
        _init(conn)
        row = conn.execute("SELECT text FROM conversations WHERE contact_id = ?", [contact_id]).fetchone()
        if row and _similar(str(row["text"] or ""), text) >= 0.9:
            pass
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
                contact_id, contact_name, window_title, text, score,
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
        return data


def delete(contact_id: str) -> bool:
    with _connect() as conn:
        _init(conn)
        changed = conn.execute("DELETE FROM conversations WHERE contact_id = ?", [contact_id]).rowcount
        conn.commit()
        return bool(changed)
