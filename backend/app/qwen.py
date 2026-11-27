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

from . import ai_common, config


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
    return ai_common.extract_json(text)


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


def review_text(text: str, case: dict[str, Any]) -> dict[str, Any]:
    case_brief = {
        "title": case.get("title"),
        "category": case.get("category"),
        "content": str(case.get("content", ""))[:2000],
        "risk_score": case.get("risk_score"),
        "scam_type": case.get("scam_type"),
        "summary": case.get("summary"),
    }
    prompt = (
        "你是反诈复核员。系统在数据库中命中了一个相似案例，请复核用户文本是否与该案例一致，"
        "并给出最终风险判断。只输出 JSON："
        "{\"confirmed\":true或false,\"confidence\":0到100,\"risk_score\":0到100,"
        "\"scam_type\":\"\",\"summary\":\"\",\"signals\":[{\"label\":\"\","
        "\"dimension\":\"script|financial|info|channel|identity\",\"weight\":0,"
        "\"evidence\":\"\"}],\"suggestions\":[]}。"
    )
    payload = {
        "model": config.QWEN_TEXT_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "【数据库案例】" + json.dumps(case_brief, ensure_ascii=False)
                + "\n【用户文本】" + text[:12000],
            },
        ],
    }
    data = _extract_json(_post(payload))
    if not data:
        raise QwenError("Qwen 复核结果不是有效 JSON")
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


