"""线程安全的短 TTL 内存缓存：相同文本短时间内直接返回。"""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from typing import Any

MAX_ENTRIES = 512


class TTLCache:
    def __init__(self, ttl_seconds: int = 600, max_entries: int = MAX_ENTRIES) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < now:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return copy.deepcopy(value)

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = (time.time() + self.ttl, copy.deepcopy(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


text_cache = TTLCache()
