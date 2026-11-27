"""DeepSeek V4.1 Flash 适配层。

官方模型名：deepseek-flash
能力：原生文本 + 图像理解，1M 上下文。
接口：OpenAI 兼容的 /chat/completions。
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from . import ai_common, config


class DeepSeekError(RuntimeError):
    """DeepSeek 调用失败。"""


def is_enabled() -> bool:
    return bool(config.DEEPSEEK_ENABLED)


def status() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "provider": "deepseek",
        "base_url": config.DEEPSEEK_BASE_URL,
        "model": config.DEEPSEEK_MODEL,
        "vision_model": config.DEEPSEEK_VISION_MODEL,
        "capabilities": ["text", "image"],
        "note": "已启用 DeepSeek V4.1 Flash（文本 + 视觉）" if is_enabled() else "未配置 DEEPSEEK_API_KEY",
    }


def _post(payload: dict[str, Any]) -> str:
    if not is_enabled():
        raise DeepSeekError("未配置 DEEPSEEK_API_KEY")
    url = config.DEEPSEEK_BASE_URL + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=config.DEEPSEEK_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise DeepSeekError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise DeepSeekError(f"DeepSeek 请求失败：{exc}") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError(f"DeepSeek 返回格式异常：{str(data)[:300]}") from exc
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content)


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
        "model": config.DEEPSEEK_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": TEXT_SYSTEM_PROMPT},
            {"role": "user", "content": text[:12000]},
        ],
    }
    data = ai_common.extract_json(_post(payload))
    if not data:
        raise DeepSeekError("DeepSeek 文本结果不是有效 JSON")
    return data


REVIEW_PROMPT = """你是反诈复核员。系统在数据库中命中了一个相似案例，请复核用户文本是否与该案例一致，并给出最终风险判断。
只输出 JSON，不要输出 Markdown，结构如下：
{
  "confirmed": true或false,
  "confidence": 0到100的整数,
  "risk_score": 0到100的整数,
  "scam_type": "诈骗类型",
  "summary": "不超过100字的复核结论",
  "signals": [{"label": "风险点", "dimension": "script|financial|info|channel|identity", "weight": 0到30, "evidence": "原文片段"}],
  "suggestions": ["处置建议"]
}
如果用户文本与案例一致，confirmed=true；如果只是相似但风险较低，confirmed=false 并给出较低评分。"""


def review_text(text: str, case: dict[str, Any]) -> dict[str, Any]:
    case_brief = {
        "title": case.get("title"),
        "category": case.get("category"),
        "content": str(case.get("content", ""))[:2000],
        "risk_score": case.get("risk_score"),
        "scam_type": case.get("scam_type"),
        "summary": case.get("summary"),
    }
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": REVIEW_PROMPT},
            {
                "role": "user",
                "content": "【数据库案例】" + json.dumps(case_brief, ensure_ascii=False)
                + "\n【用户文本】" + text[:12000],
            },
        ],
    }
    data = ai_common.extract_json(_post(payload))
    if not data:
        raise DeepSeekError("DeepSeek 复核结果不是有效 JSON")
    return data


IMAGE_GROUP_PROMPT = """你是多图联合反诈分析员。用户同时上传了多张图片，系统已分别提取每张图片的 OCR 文本、单图风险点和摘要。
请横向比对所有图片，判断它们是否属于同一诈骗场景、是否互相印证、是否存在矛盾，并给出整体结论。
只输出 JSON，不要输出 Markdown，结构如下：
{
  "risk_score": 0到100的整数,
  "scam_type": "诈骗类型",
  "summary": "不超过120字的整体结论，必须说明多图之间的关联",
  "signals": [{"label": "风险点", "dimension": "script|financial|info|channel|identity", "weight": 0到30, "evidence": "对应图片/文字依据"}],
  "suggestions": ["处置建议"],
  "relationships": ["图片1的转账凭证与图片2的客服话术互相印证", "图片3的二维码与图片1的收款方一致"],
  "image_findings": [{"index": 1, "role": "该图在骗局中的角色", "risk_points": ["该图的关键风险点"]}]
}
重点关注：多张图是否构成完整诈骗链路、金额/账号/二维码/客服身份是否前后一致、是否存在伪造与矛盾。"""


def analyze_image_group(text: str, note: str, images: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": IMAGE_GROUP_PROMPT},
            {
                "role": "user",
                "content": "【用户文本】" + (text or "（无）")[:4000]
                + "\n【用户备注】" + (note or "（无）")[:500]
                + "\n【图片信息】" + json.dumps(images, ensure_ascii=False)[:16000],
            },
        ],
    }
    data = ai_common.extract_json(_post(payload))
    if not data:
        raise DeepSeekError("DeepSeek 多图联合结果不是有效 JSON")
    return data


def analyze_image(image_bytes: bytes, content_type: str) -> dict[str, Any]:
    data_url = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    payload = {
        "model": config.DEEPSEEK_VISION_MODEL,
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
    data = ai_common.extract_json(_post(payload))
    if not data:
        raise DeepSeekError("DeepSeek 视觉结果不是有效 JSON")
    return data
