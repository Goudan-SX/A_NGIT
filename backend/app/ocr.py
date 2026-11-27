"""Windows 本地 OCR 兜底。

优先使用 Qwen-VL 做图片理解；没有配置 Qwen 时，调用 Windows 自带的
Windows.Media.Ocr（无需联网、无需额外安装）提取截图中的文字，
再交给本地规则引擎分析。非 Windows 环境会平稳返回空字符串。
"""
from __future__ import annotations

import json
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

# Windows OCR 会把左右结构的汉字误拆成“偏旁 + 部件”两个字符，
# 这里按常见拆字模式还原。这些偏旁字符（亻/扌）在正常文本中几乎不会
# 单独出现，因此替换是安全的。映射均符合汉字结构，不会误改正常文本。
_SPLIT_CHAR_FIX: dict[str, str] = {
    # 亻（单人旁）被拆
    "亻尔": "你", "亻门": "们", "亻乍": "作", "亻故": "做",
    "亻主": "住", "亻十": "什", "亻也": "他", "亻可": "何",
    "亻立": "位", "亻本": "体", "亻化": "化",
    # 扌（提手旁）被拆
    "扌巴": "把", "扌立": "拉", "扌丁": "打", "扌白": "拍",
    "扌戈": "找", "扌老": "拷", "扌安": "按", "扌召": "招",
    "扌发": "拨", "扌争": "挣", "扌齐": "挤", "扌卜": "扑",
    "扌比": "批",
    # 讠（言字旁）被拆
    "讠乍": "诈", "讠己": "记", "讠义": "议", "讠十": "计",
    "讠仑": "论", "讠正": "证", "讠斥": "诉", "讠炎": "谈",
    "讠兑": "说", "讠吾": "语",
}


def _fix_split_chars(text: str) -> str:
    """还原被 Windows OCR 拆成偏旁的左右结构汉字。"""
    for wrong, right in _SPLIT_CHAR_FIX.items():
        text = text.replace(wrong, right)
    return text


def is_available() -> bool:
    return sys.platform == "win32" and SCRIPT_PATH.exists()


def _normalize(text: str) -> str:
    """Windows OCR 会在汉字之间插入空格，这里做轻量清洗。"""
    value = text.translate(_TRANSLATION).replace("\u3000", " ")
    value = re.sub(r"[ \t]+", " ", value)
    # 去掉汉字之间的空格，保留英文单词与数字之间的空格
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"\s*([：:，,。.；;！!？?])\s*", r"\1", value)
    # 还原被 OCR 拆成偏旁的左右结构汉字（在去空格之后，确保“亻 尔”先合并为“亻尔”）
    value = _fix_split_chars(value)
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
        # 隐藏 PowerShell 控制台，避免托盘 OCR 兜底时反复闪窗。
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=0x08000000,
            startupinfo=startupinfo,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    output = (result.stdout or "").strip()
    if not output or output == "__NO_ENGINE__":
        return ""
    return _normalize(output)

def extract_lines(image_path: str | Path, timeout: int = 30) -> list[dict]:
    """返回 OCR 行及包围盒，供区分左右两侧消息。"""
    if not is_available():
        return []
    path = str(Path(image_path).resolve())
    command = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT_PATH), "-Path", path, "-Json",
    ]
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, creationflags=0x08000000,
            startupinfo=startupinfo,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads((result.stdout or "").strip() or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    lines = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        text = _normalize(str(item.get("text", "")))
        if text:
            lines.append({
                "text": text,
                "x": int(item.get("x", 0)),
                "y": int(item.get("y", 0)),
                "w": int(item.get("w", 0)),
                "h": int(item.get("h", 0)),
            })
    return lines
