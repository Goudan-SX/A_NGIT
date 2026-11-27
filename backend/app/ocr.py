"""Windows 本地 OCR 兜底。

优先使用 Qwen-VL 做图片理解；没有配置 Qwen 时，调用 Windows 自带的
Windows.Media.Ocr（无需联网、无需额外安装）提取截图中的文字，
再交给本地规则引擎分析。非 Windows 环境会平稳返回空字符串。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("ocr_windows.ps1")

# 全角数字与常见标点归一化
_TRANSLATION = str.maketrans(
    "０１２３４５６７８９：，。；！？（）【】“”‘’",
    "0123456789:,.;!?()[]\"\"''",
)


def is_available() -> bool:
    return sys.platform == "win32" and SCRIPT_PATH.exists()


def _normalize(text: str) -> str:
    """Windows OCR 会在汉字之间插入空格，这里做轻量清洗。"""
    value = text.translate(_TRANSLATION).replace("\u3000", " ")
    value = re.sub(r"[ \t]+", " ", value)
    # 去掉汉字之间的空格，保留英文单词与数字之间的空格
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"\s*([：:，,。.；;！!？?])\s*", r"\1", value)
    return value.strip()


def extract_text(image_path: str | Path, timeout: int = 45) -> str:
    if not is_available():
        return ""
    path = str(Path(image_path).resolve())
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT_PATH),
        "-Path",
        path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    output = (result.stdout or "").strip()
    if not output or output == "__NO_ENGINE__":
        return ""
    return _normalize(output)
