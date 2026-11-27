"""文本预处理：全角转半角、去干扰符号、压缩空白，降低简单绕过。"""
from __future__ import annotations

import re
import unicodedata

_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_SPOOFERS = re.compile(r"[*_~|^]+")


def preprocess_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u3000", " ")
    value = _INVISIBLE.sub("", value)
    value = _SPOOFERS.sub("", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    # 去掉汉字之间的空格："刷 单" -> "刷单"
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    return value.strip()


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", preprocess_text(text))
