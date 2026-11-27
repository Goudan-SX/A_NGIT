"""Qwen（通义千问）多模态适配层。

优先使用阿里云百炼 OpenAI 兼容接口：
  - 文本理解：QWEN_TEXT_MODEL（默认 qwen-plus）
  - 图片理解：QWEN_VL_MODEL（默认 qwen-vl-max）
  - 语音转写：QWEN_AUDIO_MODEL（默认 qwen3-asr-flash）

未配置 QWEN_API_KEY 时，所有方法都会平稳降级，不影响本地规则引擎。
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from typing import Any

from . import config


class QwenError(RuntimeError):
    """Qwen 调用失败。"""


def is_enabled() -> bool:
    return bool(config.QWEN_API_KEY)


def status() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "provider": "qwen",
        "base_url": config.QWEN_BASE_URL,
        "text_model": config.QWEN_TEXT_MODEL,
        "vision_model": config.QWEN_VL_MODEL,
        "audio_model": config.QWEN_AUDIO_MODEL,
        "note": "已启用 Qwen 多模态增强" if is_enabled() else "未配置 QWEN_API_KEY，当前使用本地规则引擎",
    }


def _post(payload: dict[str, Any]) -> str:
    if not is_enabled():
        raise QwenError("未配置 QWEN_API_KEY")
    url = config.QWEN_BASE_URL + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.QWEN_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=config.QWEN_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise QwenError(f"Qwen HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001 - 网络错误统一向上抛出可读信息
        raise QwenError(f"Qwen 请求失败：{exc}") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QwenError(f"Qwen 返回格式异常：{str(data)[:300]}") from exc
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content)


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型回复中提取 JSON，兼容 JSON 代码块和前后说明文字。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith(chr(96) * 3):
        cleaned = re.sub(r"^" + chr(96) * 3 + r"(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*" + chr(96) * 3 + r"$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group())
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


TEXT_SYSTEM_PROMPT = """你是一名专业的反诈分析师。请分析用户提供的聊天文本，识别诈骗风险。
只输出 JSON，不要输出 Markdown 或多余解释，结构如下：
{
  "risk_score": 0到100的整数,
  "scam_type": "诈骗类型，如刷单返利/冒充客服退款/冒充公检法/虚假投资理财/网络贷款/杀猪盘/游戏交易/信息窃取",
  "summary": "不超过100字的结论",
  "signals": [{"label": "风险点", "dimension": "script|financial|info|channel|identity", "weight": 0到30, "evidence": "原文片段"}],
  "suggestions": ["处置建议"]
}
评分维度：话术操控20分、资金诱导30分、信息窃取25分、渠道异常15分、身份伪装10分。
如果文本是科普或提醒性质，请降低评分。"""

VISION_PROMPT = """你是反诈多模态分析助手。请识别这张聊天截图/二维码/转账凭证/名片中的信息，并判断诈骗风险。
只输出 JSON，不要输出 Markdown，结构如下：
{
  "ocr_text": "图片中的完整文字，尽量逐字转写",
  "risk_score": 0到100的整数,
  "scam_type": "诈骗类型",
  "summary": "不超过100字的结论",
  "signals": [{"label": "风险点", "dimension": "script|financial|info|channel|identity", "weight": 0到30, "evidence": "图片中的依据"}],
  "suggestions": ["处置建议"]
}
重点关注：转账/垫付、验证码、屏幕共享、二维码收款、伪造官方页面、身份证银行卡照片、陌生链接。"""


def analyze_text(text: str) -> dict[str, Any]:
    payload = {
        "model": config.QWEN_TEXT_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": TEXT_SYSTEM_PROMPT},
            {"role": "user", "content": text[:6000]},
        ],
    }
    content = _post(payload)
    data = _extract_json(content)
    if not data:
        raise QwenError("Qwen 文本结果不是有效 JSON")
    return data


def analyze_image(image_bytes: bytes, content_type: str) -> dict[str, Any]:
    data_url = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    payload = {
        "model": config.QWEN_VL_MODEL,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    content = _post(payload)
    data = _extract_json(content)
    if not data:
        raise QwenError("Qwen 图片结果不是有效 JSON")
    return data


def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
    """调用 Qwen ASR。不同账号可用的模型名可能不同，可通过 QWEN_AUDIO_MODEL 覆盖。"""
    data_url = f"data:{content_type};base64,{base64.b64encode(audio_bytes).decode('ascii')}"
    payload = {
        "model": config.QWEN_AUDIO_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请把这段语音完整转写为中文文本，只输出转写结果。"},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    },
                ],
            }
        ],
    }
    content = _post(payload)
    if not isinstance(content, str) or not content.strip():
        raise QwenError("Qwen 语音转写结果为空")
    return content.strip()


def qwen_signals_to_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
    """把 Qwen 返回的风险点转换成统一证据结构。"""
    dimension_map = {
        "script": "script",
        "financial": "financial",
        "info": "info",
        "channel": "channel",
        "identity": "identity",
    }
    result = []
    for index, item in enumerate(data.get("signals") or []):
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension", "script"))
        weight = item.get("weight", 8)
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            weight = 8
        result.append({
            "id": f"qwen_{index}",
            "label": str(item.get("label", "语义风险"))[:40],
            "dim": dimension_map.get(dimension, "script"),
            "weight": max(1, min(30, weight)),
            "severity": "high" if weight >= 12 else "medium",
            "count": 1,
            "evidence": str(item.get("evidence", ""))[:90],
            "protective": False,
            "source": "qwen",
        })
    return result
