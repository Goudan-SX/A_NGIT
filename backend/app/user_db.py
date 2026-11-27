"""用户中心数据访问层（SQL Server [user] 库）。

设计要点：
- 共享表 + user_id 租户标识列，所有查询都必须带 user_id，禁止跨用户查询；
- user_id 建索引；isdeleted 软删除，误删可恢复；
- user_id 从 1001 开始自增，删除不退不补；
- 登录按 username（邮箱）匹配，数据管理按 user_id。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyodbc

from . import config, db, tenant

ROOT_USERNAME = "root"
COOKIE_NAME = "guardian_user"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 200_000
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_schema_lock = threading.Lock()
_schema_ready = False


class UserAuthError(ValueError):
    """账号、密码或权限错误。"""


def _connection_string(database: str) -> str:
    parts = [
        f"DRIVER={{{config.DB_DRIVER}}}",
        f"SERVER={config.DB_SERVER}",
        f"DATABASE={database}",
        f"Encrypt={config.DB_ENCRYPT}",
        "TrustServerCertificate=yes",
        f"Connection Timeout={config.DB_TIMEOUT}",
    ]
    if config.DB_TRUSTED:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={config.DB_USER}")
        parts.append(f"PWD={config.DB_PASSWORD}")
    return ";".join(parts) + ";"


def _connect(database: str | None = None, *, autocommit: bool = False) -> pyodbc.Connection:
    name = database or config.USER_DB_NAME
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("USER_DB_NAME 只允许字母、数字和下划线")
    return pyodbc.connect(_connection_string(name), autocommit=autocommit, timeout=config.DB_TIMEOUT)


def _row_to_dict(cursor: pyodbc.Cursor, row: Any) -> dict[str, Any]:
    data = dict(zip([item[0] for item in cursor.description], row))
    for key, value in list(data.items()):
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat(sep=" ", timespec="seconds")
    return data


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}", salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    expected, _ = hash_password(password, salt)
    return hmac.compare_digest(expected, stored_hash)


def ensure_database() -> None:
    """首次使用时自动创建 [user] 库、表结构和 root 管理员账号。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        db_name = config.USER_DB_NAME
        master = _connect("master", autocommit=True)
        try:
            cur = master.cursor()
            if not cur.execute("SELECT DB_ID(?)", db_name).fetchone()[0]:
                db.create_database(cur, db_name)
        finally:
            master.close()

        schema_path = Path(__file__).resolve().parent.parent / "database" / "user_schema.sql"
        conn = _connect(db_name)
        try:
            db.execute_script(conn, schema_path.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()
        _seed_root()
        _schema_ready = True


def _seed_root() -> None:
    # 注意：在 ensure_database 的 schema 锁内调用，不能再次进入 query_one/ensure_database。
    conn = _connect()
    try:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT user_id FROM dbo.users WHERE username = ? AND isdeleted = 0",
            (ROOT_USERNAME,),
        ).fetchone()
        if exists:
            return
        password_hash, salt = hash_password(config.ROOT_PASSWORD)
        cur.execute(
            """
            INSERT INTO dbo.users (username, user_key, password_hash, password_salt, role)
            VALUES (?, ?, ?, ?, N'root')
            """,
            ROOT_USERNAME,
            tenant.make_user_key(1001, ROOT_USERNAME),
            password_hash,
            salt,
        )
        conn.commit()
    finally:
        conn.close()


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    ensure_database()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [_row_to_dict(cur, row) for row in cur.fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = query_all(sql, params)
    return rows[0] if rows else None


@contextmanager
def transaction():
    ensure_database()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def validate_credentials(username: str, password: str) -> None:
    if not username:
        raise UserAuthError("请输入邮箱地址")
    if username != ROOT_USERNAME and not EMAIL_RE.fullmatch(username):
        raise UserAuthError("请输入有效的邮箱地址")
    if len(username) > 254:
        raise UserAuthError("邮箱地址过长")
    if not password or len(password) < 6:
        raise UserAuthError("密码至少 6 位")
    if len(password) > 128:
        raise UserAuthError("密码不能超过 128 位")


def login_or_register(username: str, password: str) -> tuple[dict[str, Any], bool]:
    """邮箱不存在时自动注册并登录，存在时校验密码后登录。"""
    username = normalize_username(username)
    validate_credentials(username, password)
    row = query_one(
        "SELECT * FROM dbo.users WHERE username = ? AND isdeleted = 0",
        (username,),
    )
    created = False
    if row:
        if not verify_password(password, row["password_hash"], row["password_salt"]):
            raise UserAuthError("密码错误，请重新输入")
        with transaction() as conn:
            conn.cursor().execute(
                "UPDATE dbo.users SET last_login_at = SYSDATETIME(), updated_at = SYSDATETIME() WHERE user_id = ?",
                (row["user_id"],),
            )
    else:
        password_hash, salt = hash_password(password)
        try:
            with transaction() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO dbo.users
                        (username, password_hash, password_salt, role, last_login_at)
                    OUTPUT INSERTED.user_id
                    VALUES (?, ?, ?, N'user', SYSDATETIME())
                    """,
                    username,
                    password_hash,
                    salt,
                )
                user_id = int(cur.fetchone()[0])
                cur.execute(
                    "UPDATE dbo.users SET user_key = ? WHERE user_id = ?",
                    (tenant.make_user_key(user_id, username), user_id),
                )
        except pyodbc.IntegrityError as exc:
            raise UserAuthError("该邮箱正在被注册，请重试") from exc
        created = True
        row = query_one("SELECT * FROM dbo.users WHERE user_id = ?", (user_id,))
    if not row:
        raise UserAuthError("用户创建失败，请重试")
    return row, created


def get_user(user_id: int) -> dict[str, Any] | None:
    return query_one(
        "SELECT * FROM dbo.users WHERE user_id = ? AND isdeleted = 0",
        (int(user_id),),
    )


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with transaction() as conn:
        conn.cursor().execute(
            """
            INSERT INTO dbo.user_sessions (user_id, user_key, token_hash, expires_at)
            VALUES (?, (SELECT TOP 1 user_key FROM dbo.users WHERE user_id = ?), ?,
                    DATEADD(day, ?, SYSDATETIME()))
            """,
            (int(user_id), int(user_id), token_hash, SESSION_DAYS),
        )
    return token


def resolve_session(token: str | None) -> dict[str, Any] | None:
    token = (token or "").strip()
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return query_one(
        """
        SELECT u.*
        FROM dbo.user_sessions s
        JOIN dbo.users u ON u.user_id = s.user_id
        WHERE s.token_hash = ? AND s.isdeleted = 0
          AND s.expires_at > SYSDATETIME() AND u.isdeleted = 0
        """,
        (token_hash,),
    )


def revoke_session(token: str | None) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with transaction() as conn:
        affected = conn.cursor().execute(
            "UPDATE dbo.user_sessions SET isdeleted = 1 WHERE token_hash = ?",
            (token_hash,),
        ).rowcount
    return bool(affected)


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    """返回给前端的用户信息，绝不包含密码与 API Key 明文。"""
    cfg = api_config(row)
    return {
        "id": int(row["user_id"]),
        "username": row["username"],
        "user_key": row.get("user_key") or tenant.make_user_key(int(row["user_id"]), row["username"]),
        "role": row["role"],
        "created_at": row.get("created_at"),
        "last_login_at": row.get("last_login_at"),
        "api": cfg,
    }


def api_config(row: dict[str, Any]) -> dict[str, Any]:
    key = (row.get("api_key") or "").strip()
    return {
        "base_url": row.get("api_base_url") or "",
        "model": row.get("api_model") or "",
        "vision_model": row.get("api_vision_model") or "",
        "has_key": bool(key),
        "key_masked": (key[:4] + "••••" + key[-4:]) if len(key) > 10 else ("••••••" if key else ""),
        "configured": bool(row.get("api_base_url") and key and row.get("api_model")),
        "status": row.get("api_status") or "unknown",
        "checked_at": row.get("api_checked_at"),
    }


def save_api_config(user_id: int, *, base_url: str, api_key: str,
                    model: str, vision_model: str) -> dict[str, Any]:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE dbo.users
            SET api_base_url = ?, api_key = ?, api_model = ?, api_vision_model = ?,
                api_status = N'unknown', api_checked_at = NULL,
                updated_at = SYSDATETIME()
            WHERE user_id = ? AND isdeleted = 0
            """,
            (base_url, api_key, model, vision_model, int(user_id)),
        )
    row = get_user(int(user_id))
    if not row:
        raise UserAuthError("用户不存在")
    upsert_user_data(int(user_id), "api_profile", json.dumps({
        "base_url": base_url, "model": model, "vision_model": vision_model,
        "has_key": bool(api_key),
    }, ensure_ascii=False))
    return row


def set_api_status(user_id: int, status: str) -> None:
    if status not in {"ok", "error", "unknown"}:
        status = "unknown"
    with transaction() as conn:
        conn.cursor().execute(
            """
            UPDATE dbo.users
            SET api_status = ?, api_checked_at = SYSDATETIME(), updated_at = SYSDATETIME()
            WHERE user_id = ? AND isdeleted = 0
            """,
            (status, int(user_id)),
        )


def upsert_user_data(user_id: int, data_key: str, value: str) -> None:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE dbo.user_data
            SET data_value = ?, updated_at = SYSDATETIME()
            WHERE user_id = ? AND data_key = ? AND isdeleted = 0
            """,
            (value, int(user_id), data_key),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO dbo.user_data (user_id, user_key, data_key, data_value)
                VALUES (?, (SELECT TOP 1 user_key FROM dbo.users WHERE user_id = ?), ?, ?)
                """,
                (int(user_id), int(user_id), data_key, value),
            )


def get_user_data(user_id: int, data_key: str) -> str | None:
    row = query_one(
        """
        SELECT data_value FROM dbo.user_data
        WHERE user_id = ? AND data_key = ? AND isdeleted = 0
        """,
        (int(user_id), data_key),
    )
    return row["data_value"] if row else None


def purge_expired_sessions() -> int:
    """删除已过期的登录会话（时效性数据维护）。"""
    with transaction() as conn:
        changed = conn.cursor().execute(
            "DELETE FROM dbo.user_sessions WHERE expires_at < SYSDATETIME() OR isdeleted = 1"
        ).rowcount
    return int(changed or 0)


def list_users() -> list[dict[str, Any]]:
    """仅 root 管理员可调用：查看全部用户（含已软删除）。"""
    rows = query_all(
        """
        SELECT user_id, username, user_key, role, api_base_url, api_model, api_status,
               isdeleted, created_at, updated_at, last_login_at
        FROM dbo.users
        ORDER BY user_id
        """
    )
    for row in rows:
        row["user_id"] = int(row["user_id"])
        row["id"] = row["user_id"]
        row["isdeleted"] = bool(row["isdeleted"])
    return rows


def health() -> dict[str, Any]:
    ensure_database()
    conn = _connect()
    try:
        cur = conn.cursor()
        version = cur.execute("SELECT @@VERSION").fetchone()[0].splitlines()[0]
        return {"ok": True, "database": config.USER_DB_NAME, "server": version}
    finally:
        conn.close()
