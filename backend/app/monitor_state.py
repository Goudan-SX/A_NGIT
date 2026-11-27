"""本地托盘最近一次监测结果（仅内存，不落原始文本）。"""
from __future__ import annotations

import copy
import threading
import time
import uuid

from . import tenant

_lock = threading.Lock()
_latest: dict[int, dict] = {}


def publish(*, text: str, result: dict, source: str = "tray", window: str = "") -> dict:
    payload = {
        "id": uuid.uuid4().hex,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "window": window,
        "text": text or "",
        "result": result or {},
    }
    with _lock:
        _latest[tenant.user_id()] = payload
    return copy.deepcopy(payload)


def latest() -> dict | None:
    with _lock:
        payload = _latest.get(tenant.user_id())
        return copy.deepcopy(payload) if payload else None
