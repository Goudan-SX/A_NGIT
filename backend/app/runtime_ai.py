"""运行时 OpenAI 兼容 API 配置。

用户在网页端填写 API 地址 / Key / 模型后，后端把配置保存在 [user] 库，
并在进程内激活；DeepSeek 适配层优先使用这里的配置，未配置时回退 .env。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import config

_lock = threading.Lock()
_active: dict[str, Any] | None = None


class ApiConfigError(ValueError):
    """API 配置不合法。"""


def normalize_base_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    value = value.rstrip("/")
    lower = value.lower()
    for suffix in ("/chat/completions", "/models"):
        if lower.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
            lower = value.lower()
    return value


def validate(*, base_url: str, api_key: str, model: str) -> None:
    if not base_url:
        raise ApiConfigError("请填写 API 地址")
    if not re.match(r"^https?://[^\s/]+", base_url, re.IGNORECASE):
        raise ApiConfigError("API 地址格式不正确，需要以 http:// 或 https:// 开头")
    if not api_key:
        raise ApiConfigError("请填写 API Key")
    if len(api_key) > 500:
        raise ApiConfigError("API Key 过长")
    if not model:
        raise ApiConfigError("请填写模型名称")
    if len(model) > 120:
        raise ApiConfigError("模型名称过长")


def activate(row: dict[str, Any]) -> dict[str, Any] | None:
    """把数据库中的 API 配置装载为当前生效配置；配置不完整时清除。"""
    global _active
    cfg = {
        "user_id": int(row["user_id"]),
        "base_url": normalize_base_url(row.get("api_base_url") or ""),
        "api_key": (row.get("api_key") or "").strip(),
        "model": (row.get("api_model") or "").strip(),
        "vision_model": (row.get("api_vision_model") or "").strip(),
    }
    with _lock:
        if cfg["base_url"] and cfg["api_key"] and cfg["model"]:
            cfg["vision_model"] = cfg["vision_model"] or cfg["model"]
            _active = cfg
            return dict(cfg)
        _active = None
        return None


def deactivate() -> None:
    global _active
    with _lock:
        _active = None


def current() -> dict[str, Any] | None:
    with _lock:
        return dict(_active) if _active else None


def has_override() -> bool:
    cfg = current()
    return bool(cfg and cfg.get("api_key"))


def resolve() -> dict[str, Any]:
    """返回当前真正用于调用的配置；用户配置优先，否则回退 .env。"""
    cfg = current()
    if cfg and cfg.get("api_key"):
        return {
            "source": "user",
            "base_url": cfg["base_url"],
            "api_key": cfg["api_key"],
            "model": cfg["model"],
            "vision_model": cfg.get("vision_model") or cfg["model"],
            "timeout": config.DEEPSEEK_TIMEOUT,
        }
    return {
        "source": "env",
        "base_url": config.DEEPSEEK_BASE_URL,
        "api_key": config.DEEPSEEK_API_KEY,
        "model": config.DEEPSEEK_MODEL,
        "vision_model": config.DEEPSEEK_VISION_MODEL,
        "timeout": config.DEEPSEEK_TIMEOUT,
    }


def test_connection(cfg: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    """调用一次最小 chat/completions 请求，检测 OpenAI 兼容接口是否可用。"""
    base_url = normalize_base_url(cfg.get("base_url") or "")
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()
    try:
        validate(base_url=base_url, api_key=api_key, model=model)
    except ApiConfigError as exc:
        return {"ok": False, "message": str(exc), "latency_ms": 0, "http_status": None}

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Guardian-AI/2.0",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=max(3, min(int(timeout), 20))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status_code = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        latency = int((time.time() - started) * 1000)
        hints = {
            400: "请求被拒绝，请检查模型名称或 API 地址",
            401: "API Key 无效或已过期",
            403: "API Key 没有访问权限",
            404: "接口不存在，请检查 API 地址（通常需要包含 /v1）",
            429: "请求过于频繁或额度不足",
        }
        message = hints.get(exc.code, f"接口返回 HTTP {exc.code}")
        return {"ok": False, "message": f"{message}：{detail[:160]}", "latency_ms": latency,
                "http_status": exc.code}
    except urllib.error.URLError as exc:
        latency = int((time.time() - started) * 1000)
        reason = str(getattr(exc, "reason", exc))
        lowered = reason.lower()
        if "refused" in lowered or "积极拒绝" in reason:
            message = "连接被拒绝：请确认 API 地址正确且服务可访问"
        elif "timed out" in lowered or "超时" in reason:
            message = "连接超时：请检查网络或代理设置"
        elif "name or service" in lowered or "getaddrinfo" in lowered:
            message = "域名解析失败：请检查 API 地址"
        else:
            message = f"无法连接：{reason[:160]}"
        return {"ok": False, "message": message, "latency_ms": latency, "http_status": None}
    except Exception as exc:  # noqa: BLE001 - 网络错误统一转成可读提示
        latency = int((time.time() - started) * 1000)
        return {"ok": False, "message": f"无法连接：{exc}", "latency_ms": latency, "http_status": None}

    latency = int((time.time() - started) * 1000)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "message": "接口返回的不是 JSON，可能不是 OpenAI 兼容格式",
                "latency_ms": latency, "http_status": status_code}
    if isinstance(data, dict) and data.get("error"):
        error = data["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        return {"ok": False, "message": f"接口返回错误：{message}", "latency_ms": latency,
                "http_status": status_code}
    if not isinstance(data, dict) or not data.get("choices"):
        return {"ok": False, "message": "接口未返回 choices，可能不是 OpenAI 兼容格式",
                "latency_ms": latency, "http_status": status_code}
    return {"ok": True, "message": f"连接成功，模型 {model} 可用", "latency_ms": latency,
            "http_status": status_code}
