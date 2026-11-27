"""请求级租户上下文。

统一键名规则（当前版本）：
- 用户键：u{user_id}:{username}，例如 u1001:root
- 对话键：{user_key}:c:{contact_id}
所有用户数据表都保存 user_id + user_key，查询必须带租户条件，禁止跨用户读取。
未登录 / 托盘 / 后台任务默认使用 root（1001），保证历史测试数据归属 root。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

DEFAULT_USER_ID = 1001
DEFAULT_USERNAME = "root"


def make_user_key(user_id: int, username: str) -> str:
    name = (username or DEFAULT_USERNAME).strip().lower()
    return f"u{int(user_id)}:{name}"[:300]


def make_conversation_key(user_key: str, contact_id: str) -> str:
    return f"{user_key}:c:{contact_id}"


_DEFAULT = {
    "user_id": DEFAULT_USER_ID,
    "username": DEFAULT_USERNAME,
    "user_key": make_user_key(DEFAULT_USER_ID, DEFAULT_USERNAME),
}

_current: ContextVar[dict[str, Any] | None] = ContextVar("guardian_tenant", default=None)


def set_user(user: dict[str, Any] | None) -> dict[str, Any]:
    """把当前请求的登录用户写入上下文；None 表示回退 root。"""
    if not user:
        _current.set(dict(_DEFAULT))
        return dict(_DEFAULT)
    user_id = int(user.get("user_id") or user.get("id") or DEFAULT_USER_ID)
    username = str(user.get("username") or DEFAULT_USERNAME)
    value = {
        "user_id": user_id,
        "username": username,
        "user_key": make_user_key(user_id, username),
    }
    _current.set(value)
    return value


def current() -> dict[str, Any]:
    value = _current.get()
    return dict(value) if value else dict(_DEFAULT)


def user_id() -> int:
    return int(current()["user_id"])


def user_key() -> str:
    return str(current()["user_key"])


def username() -> str:
    return str(current()["username"])
