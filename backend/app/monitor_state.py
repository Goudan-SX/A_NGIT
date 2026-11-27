"""本地托盘最近一次监测结果（仅内存，不落原始文本）。"""
from __future__ import annotations

import copy
import threading
import time
import uuid

_lock = threading.Lock()
_latest: dict = {}


def publish(*, text: str, result: dict, source: str = "tray", window: str = "") -> dict:
    global _latest
    payload = {
        "id": uuid.uuid4().hex,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "window": window,
        "text": text or "",
        "result": result or {},
    }
    with _lock:
        _latest = payload
    return copy.deepcopy(payload)


def latest() -> dict | None:
    with _lock:
        return copy.deepcopy(_latest) if _latest else None
