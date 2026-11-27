"""每次请求的外部 AI 策略上下文。"""
from __future__ import annotations

from contextvars import ContextVar

_deepseek_allowed: ContextVar[bool] = ContextVar("deepseek_allowed", default=True)


def set_deepseek_allowed(value: bool) -> None:
    _deepseek_allowed.set(bool(value))


def deepseek_allowed() -> bool:
    return bool(_deepseek_allowed.get())
