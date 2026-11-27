"""本地 API 令牌与机器身份校验。"""
from __future__ import annotations

import hashlib
import hmac
import os
import platform
import secrets
import uuid
from pathlib import Path

from fastapi import Header, HTTPException, Request, Response

from . import config

TOKEN_FILE = config.DATA_DIR / ".local_api_token"
COOKIE_NAME = "guardian_local_token"


def get_local_token() -> str:
    if config.LOCAL_API_TOKEN:
        return config.LOCAL_API_TOKEN
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(value, encoding="utf-8")
    return value


def set_token_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        get_local_token(),
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


def _candidate(request: Request, header_token: str | None) -> str:
    return (header_token or request.cookies.get(COOKIE_NAME) or "").strip()


def is_valid_request(request: Request, header_token: str | None = None) -> bool:
    candidate = _candidate(request, header_token)
    return bool(candidate) and hmac.compare_digest(candidate, get_local_token())


async def verify_token(
    request: Request,
    x_guardian_token: str | None = Header(default=None, alias="X-Guardian-Token"),
) -> None:
    if not is_valid_request(request, x_guardian_token):
        raise HTTPException(status_code=401, detail="缺少或无效的本地访问令牌")


def _machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:  # noqa: BLE001
        return ""


def machine_fingerprint() -> str:
    material = "|".join(
        [
            platform.node(),
            str(uuid.getnode()),
            _machine_guid(),
            platform.machine(),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def is_authorized_machine() -> bool:
    expected = config.AUTHORIZED_MACHINE_ID
    return bool(expected) and hmac.compare_digest(expected, machine_fingerprint())


def is_loopback_request(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"}


def external_ai_allowed(request: Request) -> bool:
    """只有配置了本机指纹、且请求来自本机回环地址时才允许外部模型。"""
    return bool(config.EXTERNAL_AI_ALLOWED) and is_authorized_machine() and is_loopback_request(request)
