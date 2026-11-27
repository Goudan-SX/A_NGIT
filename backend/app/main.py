"""Guardian-AI FastAPI 应用。

启动：
    python backend/run.py
或：
    uvicorn backend.app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import mimetypes
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import (ai_common, ai_policy, analyzer, case_library, case_matcher, config, content_store, db, deepseek,
               conversation_store, guardian, maintenance, monitor_state, ocr, qwen, repository,
               result_cache, runtime_ai, security, tenant, transaction_risk, user_db)
from .text_normalize import preprocess_text

STARTED_AT = time.time()

# 不是有效聊天对象的名字：窗口/软件通用名称，禁止作为对话库 contact_id。
GENERIC_CONTACT_NAMES = {"", "QQ", "TIM", "微信", "WeChat", "搜索", "发送", "未知用户"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.ensure_database()
        user_db.ensure_database()
        created = case_matcher.seed_cases()
        guardian.ensure_data()
        transaction_risk.ensure_rules()
        repository.add_log(
            level="success",
            event="system",
            message=f"反诈卫士服务启动，数据库连接成功；案例库共 {case_matcher.count_cases()} 条（新增种子 {created} 条）",
            meta={"cases": case_matcher.count_cases(), "seeded": created},
        )
    except Exception as exc:  # noqa: BLE001 - 启动阶段尽量给出明确提示
        print(f"[反诈卫士] 数据库初始化失败：{exc}")
    yield


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    description="反诈卫士：面向青年的 AI 诈骗识别与个人信息保护助手",
    lifespan=lifespan,
)

class ChatRoomManager:
    """内存聊天室：只保存当前会话，不写数据库。"""

    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = {}
        self.history: dict[str, list[dict[str, Any]]] = {}

    async def connect(self, room: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.rooms.setdefault(room, set()).add(websocket)
        for item in self.history.get(room, [])[-50:]:
            await websocket.send_json(item)

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        connections = self.rooms.get(room)
        if connections:
            connections.discard(websocket)
            if not connections:
                self.rooms.pop(room, None)

    async def broadcast(self, room: str, payload: dict[str, Any]) -> None:
        if payload.get("type") == "message":
            self.history.setdefault(room, []).append(payload)
            self.history[room] = self.history[room][-100:]
        dead = []
        for websocket in list(self.rooms.get(room, set())):
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(room, websocket)


chat_rooms = ChatRoomManager()


@app.middleware("http")
async def guardian_guard(request, call_next):
    """本地令牌 + 机器身份策略：API 默认拒绝无令牌请求。"""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health":
        header_token = request.headers.get("X-Guardian-Token")
        if not security.is_valid_request(request, header_token):
            return JSONResponse(status_code=401, content={"detail": "缺少或无效的本地访问令牌"})
    requested_external = request.headers.get("X-Guardian-External-AI", "true").lower() != "false"
    ai_policy.set_deepseek_allowed(security.external_ai_allowed(request) and requested_external)
    # 租户上下文：带登录 cookie 用登录用户，否则（托盘/后台/未登录）统一回退 root。
    token = request.cookies.get(user_db.COOKIE_NAME)
    try:
        user = user_db.resolve_session(token) if token else None
    except Exception:  # noqa: BLE001 - 用户库异常不阻断既有本地功能
        user = None
    tenant.set_user(user)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 请求模型
# --------------------------------------------------------------------------
class TextAnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    save: bool = True
    client_id: str = Field(default="anonymous", max_length=64)


class MonitorPublishRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    result: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="tray", max_length=40)
    window: str = Field(default="", max_length=120)


class MonitorAnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    window: str = Field(default="", max_length=120)
    client_id: str = Field(default="tray-service", max_length=64)


class MonitorLayoutRequest(BaseModel):
    image_base64: str = Field(min_length=16, max_length=12_000_000)
    mime: str = Field(default="image/png", max_length=40)


class MonitorContactRequest(BaseModel):
    image_base64: str = Field(min_length=16, max_length=12_000_000)
    mime: str = Field(default="image/png", max_length=40)
    fast: bool = False


class FeedbackRequest(BaseModel):
    is_false_positive: bool = True
    note: str = Field(default="", max_length=500)


class ReportRequest(BaseModel):
    analysis_id: int
    channel: str = Field(default="12321", max_length=32)
    note: str = Field(default="", max_length=500)


class AuthRequest(BaseModel):
    username: str = Field(default="", max_length=254)
    password: str = Field(default="", max_length=128)


class ApiConfigRequest(BaseModel):
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=120)
    vision_model: str = Field(default="", max_length=120)
    clear: bool = False


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def _log_safe(**kwargs: Any) -> None:
    try:
        repository.add_log(**kwargs)
    except Exception:  # noqa: BLE001 - 日志失败不能影响主流程
        pass


def _source_for(parts: list[dict[str, Any]], has_text: bool) -> str:
    if has_text and parts:
        return "mixed"
    if parts:
        return parts[0]["type"]
    return "text"


def _format_time(value: Any) -> str:
    return str(value or "")


def build_report_text(analysis: dict[str, Any]) -> str:
    dims = "\n".join(
        f"  - {item['name']}：{item['score']}/{item['max']}（{item['desc']}）"
        for item in analysis.get("dimensions", [])
    )
    signals = "\n".join(
        f"  - [{item.get('label')}] {item.get('evidence', '')}"
        for item in analysis.get("signals", []) if not item.get("protective")
    ) or "  未命中明显风险特征"
    pii = "\n".join(
        f"  - {item['label']}：{item['value']}（出现 {item['count']} 次）"
        for item in analysis.get("pii", [])
    ) or "  未检测到明显个人信息暴露"
    suggestions = "\n".join(f"  {index + 1}. {text}" for index, text in enumerate(analysis.get("suggestions", [])))
    return f"""反诈卫士 · 风险检测报告
============================================================
检测时间：{_format_time(analysis.get('created_at'))}
风险评分：{analysis.get('risk_score', 0)} / 100
风险等级：{analysis.get('risk_label', '')}
疑似类型：{analysis.get('scam_type', '')}

【结论】
{analysis.get('summary', '')}

【评分维度】
{dims}

【命中证据】
{signals}

【个人信息暴露】
{pii}

【处置建议】
{suggestions}

【举报渠道】
- 国家反诈中心 App / 拨打 110 报警
- 12321 网络不良与垃圾信息举报受理中心
- 银行官方客服（冻结账户、申请止付）

本报告由反诈卫士根据聊天内容自动生成，仅用于辅助判断，不构成法律意见。
============================================================
"""


# --------------------------------------------------------------------------
# 健康检查与配置
# --------------------------------------------------------------------------
def _ai_status() -> dict[str, Any]:
    deepseek_status = deepseek.status()
    qwen_status = qwen.status()
    if deepseek_status["enabled"]:
        return {
            "enabled": True,
            "provider": deepseek_status.get("provider", "deepseek"),
            "note": deepseek_status.get("note", "DeepSeek 已启用"),
            "deepseek": deepseek_status,
            "qwen": qwen_status,
        }
    if qwen_status["enabled"]:
        return {
            "enabled": True,
            "provider": "qwen",
            "note": "Qwen 多模态已启用",
            "deepseek": deepseek_status,
            "qwen": qwen_status,
        }
    return {
        "enabled": False,
        "provider": "local",
        "note": "未配置 AI Key，当前使用本地规则 + Windows OCR",
        "deepseek": deepseek_status,
        "qwen": qwen_status,
    }


@app.websocket("/ws/chat/{room}")
async def chat_websocket(websocket: WebSocket, room: str, client_id: str = "", name: str = ""):
    """WebSocket 聊天室（基于 TCP/IP，支持局域网远程对话）。

    只转发当前聊天内容，历史仅保存在内存，不写入 SQL Server。
    """
    room = (room or "demo")[:64]
    client_id = (client_id or uuid.uuid4().hex)[:64]
    display_name = (name or "访客")[:32]
    await chat_rooms.connect(room, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "message":
                continue
            text = str(data.get("text", ""))[:2000].strip()
            if not text:
                continue
            payload = {
                "type": "message",
                "id": uuid.uuid4().hex,
                "room": room,
                "client_id": client_id,
                "name": display_name,
                "text": text,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            await chat_rooms.broadcast(room, payload)
    except WebSocketDisconnect:
        chat_rooms.disconnect(room, websocket)
    except Exception:  # noqa: BLE001
        chat_rooms.disconnect(room, websocket)


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        database = db.health()
    except Exception as exc:  # noqa: BLE001
        database = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "pid": os.getpid(),
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "database": database,
        "ai": _ai_status(),
        "cases": case_matcher.count_cases(),
        "transaction_model": transaction_risk.model_info()["available"],
        "stores": {
            "text_cases": case_matcher.count_cases(),
            "image_cases": content_store.count_image_cases(),
            "staging_contents": content_store.count_staging(),
        },
    }


@app.get("/api/conversations")
def api_conversations() -> dict[str, Any]:
    return {"ok": True, "items": conversation_store.list_contacts()}


@app.get("/api/conversations/{contact_id}")
def api_conversation(contact_id: str) -> dict[str, Any]:
    item = conversation_store.get(contact_id)
    if not item:
        raise HTTPException(status_code=404, detail="对话记录不存在或已过期")
    return {"ok": True, "item": item}


@app.delete("/api/conversations/{contact_id}")
def api_delete_conversation(contact_id: str) -> dict[str, Any]:
    return {"ok": True, "deleted": conversation_store.delete(contact_id)}


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    return {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "ai": _ai_status(),
        "cases": case_matcher.count_cases(),
        "transaction_model": transaction_risk.model_info()["available"],
        "stores": {
            "text_cases": case_matcher.count_cases(),
            "image_cases": content_store.count_image_cases(),
            "staging_contents": content_store.count_staging(),
        },
        "limits": {
            "max_image_mb": config.MAX_IMAGE_MB,
            "max_audio_mb": config.MAX_AUDIO_MB,
            "max_text": 20000,
        },
    }



# --------------------------------------------------------------------------
# 用户中心：邮箱登录 / 自动注册 / 个人信息 / 每用户 OpenAI 兼容 API 配置
# --------------------------------------------------------------------------
def _current_user(request: Request) -> dict[str, Any] | None:
    return user_db.resolve_session(request.cookies.get(user_db.COOKIE_NAME))


def _activate_saved_api(user: dict[str, Any]) -> dict[str, Any] | None:
    """刷新页面时恢复该用户已保存且未标记失败的 API 配置。"""
    row = user_db.get_user(int(user["user_id"]))
    if not row:
        return None
    cfg = user_db.api_config(row)
    if not cfg["configured"] or cfg["status"] == "error":
        runtime_ai.deactivate()
        return cfg
    runtime_ai.activate(row)
    return cfg


def _test_saved_api(user: dict[str, Any]) -> dict[str, Any] | None:
    """检测已保存 API 的连通性；成功才配置到当前程序。"""
    row = user_db.get_user(int(user["user_id"]))
    if not row:
        return None
    cfg = user_db.api_config(row)
    if not cfg["configured"]:
        runtime_ai.deactivate()
        return None
    runtime_ai.activate(row)
    result = runtime_ai.test_connection({
        "base_url": cfg["base_url"],
        "api_key": row.get("api_key") or "",
        "model": cfg["model"],
    })
    user_db.set_api_status(int(user["user_id"]), "ok" if result.get("ok") else "error")
    if not result.get("ok"):
        runtime_ai.deactivate()
    return result


def _set_user_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        user_db.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=user_db.SESSION_DAYS * 24 * 3600,
    )


@app.post("/api/auth/login")
def api_auth_login(payload: AuthRequest, response: Response) -> dict[str, Any]:
    """邮箱不存在时自动注册并登录；已存在时校验密码。"""
    try:
        user, created = user_db.login_or_register(payload.username, payload.password)
    except user_db.UserAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api_check = _test_saved_api(user)
    refreshed = user_db.get_user(int(user["user_id"])) or user
    token = user_db.create_session(int(user["user_id"]))
    _set_user_cookie(response, token)
    return {
        "ok": True,
        "created": created,
        "user": user_db.public_user(refreshed),
        "api_check": api_check,
    }


@app.get("/api/auth/me")
def api_auth_me(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    if not user:
        return {"ok": True, "user": None}
    _activate_saved_api(user)
    return {"ok": True, "user": user_db.public_user(user)}


@app.post("/api/auth/logout")
def api_auth_logout(request: Request, response: Response) -> dict[str, Any]:
    user_db.revoke_session(request.cookies.get(user_db.COOKIE_NAME))
    runtime_ai.deactivate()
    response.delete_cookie(user_db.COOKIE_NAME, path="/")
    return {"ok": True}


@app.put("/api/auth/api-config")
def api_auth_save_api(payload: ApiConfigRequest, request: Request) -> dict[str, Any]:
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再同步 API 配置")
    row = user_db.get_user(int(user["user_id"]))
    if not row:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")

    if payload.clear:
        user_db.save_api_config(int(user["user_id"]), base_url="", api_key="",
                                model="", vision_model="")
        runtime_ai.deactivate()
        refreshed = user_db.get_user(int(user["user_id"])) or row
        return {"ok": True, "user": user_db.public_user(refreshed), "api_check": None}

    existing = user_db.api_config(row)
    base_url = runtime_ai.normalize_base_url(payload.base_url or existing["base_url"])
    api_key = (payload.api_key or "").strip() or (row.get("api_key") or "")
    model = (payload.model or "").strip()
    vision_model = (payload.vision_model or "").strip() or model
    try:
        runtime_ai.validate(base_url=base_url, api_key=api_key, model=model)
    except runtime_ai.ApiConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_db.save_api_config(
        int(user["user_id"]), base_url=base_url, api_key=api_key,
        model=model, vision_model=vision_model,
    )
    refreshed = user_db.get_user(int(user["user_id"]))
    api_check = _test_saved_api(refreshed or row)
    final_user = user_db.get_user(int(user["user_id"])) or refreshed or row
    return {"ok": True, "user": user_db.public_user(final_user), "api_check": api_check}


@app.post("/api/auth/api-test")
def api_auth_test_api(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    row = user_db.get_user(int(user["user_id"]))
    cfg = user_db.api_config(row or {})
    if not cfg["configured"]:
        raise HTTPException(status_code=400, detail="尚未保存完整的 API 配置")
    result = _test_saved_api(row or user)
    final_user = user_db.get_user(int(user["user_id"])) or user
    return {"ok": True, "user": user_db.public_user(final_user), "api_check": result}


@app.get("/api/admin/users")
def api_admin_users(request: Request) -> dict[str, Any]:
    """root 管理员权限预留：可查看全部用户（含软删除），普通用户禁止跨用户查询。"""
    user = _current_user(request)
    if not user or user.get("role") != "root":
        raise HTTPException(status_code=403, detail="需要 root 管理员权限")
    return {"ok": True, "items": user_db.list_users()}


@app.post("/api/admin/maintenance")
def api_admin_maintenance(request: Request) -> dict[str, Any]:
    """root 专用：执行预设的时效性数据清理（过期会话/暂存/自动案例/回收站）。"""
    user = _current_user(request)
    if not user or user.get("role") != "root":
        raise HTTPException(status_code=403, detail="需要 root 管理员权限")
    try:
        result = maintenance.run_all()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"维护任务失败：{exc}") from exc
    _log_safe(level="success", event="maintenance", message="执行数据库维护任务",
              meta=result)
    return {"ok": True, "result": result}


@app.get("/api/knowledge")
def api_knowledge() -> dict[str, Any]:
    try:
        return {"ok": True, "items": repository.list_knowledge()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取科普内容失败：{exc}") from exc


@app.get("/api/logs/stats")
def api_log_stats() -> dict[str, Any]:
    try:
        return {"ok": True, **repository.log_stats()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取日志统计失败：{exc}") from exc


@app.get("/api/guardian/provinces")
def api_guardian_provinces() -> dict[str, Any]:
    try:
        return {"ok": True, "items": guardian.list_provinces()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取案例省份失败：{exc}") from exc


@app.get("/api/guardian/cases")
def api_guardian_cases(
    province: str = "",
    category: str = "",
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return {"ok": True, "items": guardian.list_cases(province=province, category=category, limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取分省案例失败：{exc}") from exc


# ==================== 真实案例库（CSV 411 条青少年被骗案例） ====================

@app.get("/api/case-library/categories")
def api_cl_categories() -> dict[str, Any]:
    return {"ok": True, "items": case_library.list_categories()}


@app.get("/api/case-library/provinces")
def api_cl_provinces() -> dict[str, Any]:
    return {"ok": True, "items": case_library.list_provinces()}


@app.get("/api/case-library/cases")
def api_cl_cases(
    province: str = "",
    category: str = "",
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return {"ok": True, "items": case_library.list_cases(province=province, category=category, limit=limit)}


@app.get("/api/case-library/random")
def api_cl_random(province: str = "") -> dict[str, Any]:
    return {"ok": True, "item": case_library.random_case(province=province)}


@app.get("/api/case-library/science")
def api_cl_science(category: str = "") -> dict[str, Any]:
    return {"ok": True, "item": case_library.get_science(category=category)}


@app.get("/api/case-library/science/match")
def api_cl_science_match(
    risk_label: str = "",
    scam_type: str = "",
    score: int = Query(0, ge=0, le=100),
) -> dict[str, Any]:
    """根据检测结果匹配科普内容（疑似度≥70 按类型展示，否则随机）。"""
    return {"ok": True, "item": case_library.match_science_by_text(risk_label, scam_type, score)}


@app.get("/api/case-library/tips")
def api_cl_tips(count: int = Query(0, ge=0, le=50)) -> dict[str, Any]:
    return {"ok": True, "items": case_library.list_tips(count=count)}


@app.get("/api/case-library/quiz")
def api_cl_quiz(count: int = Query(5, ge=1, le=10)) -> dict[str, Any]:
    return {"ok": True, "items": case_library.list_quiz(count=count)}


@app.get("/api/stats")
def api_stats() -> dict[str, Any]:
    try:
        return {"ok": True, **repository.stats()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取统计数据失败：{exc}") from exc


@app.post("/api/transaction/risk")
def api_transaction_risk(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        result = transaction_risk.predict(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"交易风控推理失败：{exc}") from exc
    _log_safe(
        level="warning" if result["risk_level"] in {"high", "critical"} else "info",
        event="transaction",
        message=f"交易风控：{result['risk_label']} {result['risk_score']} 分",
        meta={
            "risk_score": result["risk_score"],
            "matched_rules": [item["code"] for item in result["matched_rules"]],
            "model_available": result["model_available"],
        },
    )
    return {"ok": True, **result}


@app.get("/api/transaction/model-info")
def api_transaction_model_info() -> dict[str, Any]:
    return {"ok": True, **transaction_risk.model_info()}


@app.get("/api/transaction/rules")
def api_transaction_rules() -> dict[str, Any]:
    return {"ok": True, "items": transaction_risk.list_rules()}


@app.get("/api/logs")
def api_logs(
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
    level: str = "",
    event: str = "",
) -> dict[str, Any]:
    try:
        return {"ok": True, **repository.list_logs(page=page, size=size, level=level, event=event)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取日志失败：{exc}") from exc


# --------------------------------------------------------------------------
# 文本分析
# --------------------------------------------------------------------------
def _enhance_text_with_ai(result: dict[str, Any], text: str, errors: list[str] | None = None) -> dict[str, Any]:
    if not text.strip():
        return result
    if deepseek.is_enabled():
        try:
            ai_data = deepseek.analyze_text(text)
            result = _apply_ai(result, ai_data, source="text", provider="deepseek")
            result["engine"]["note"] = "Guardian-AI · DeepSeek V4.1 语义精判"
            return result
        except Exception as exc:  # noqa: BLE001
            if errors is not None:
                errors.append(f"DeepSeek 文本分析失败：{str(exc)[:160]}")
            result["engine"]["note"] = f"DeepSeek 调用失败，已尝试降级：{str(exc)[:120]}"
    if qwen.is_enabled():
        try:
            ai_data = qwen.analyze_text(text)
            result = _apply_ai(result, ai_data, source="text", provider="qwen")
            result["engine"]["note"] = "Guardian-AI · Qwen 语义精判"
        except Exception as exc:  # noqa: BLE001
            result["engine"]["note"] = f"Qwen 文本调用失败，已降级为本地规则：{str(exc)[:120]}"
            if errors is not None:
                errors.append(f"Qwen 文本分析失败：{str(exc)[:160]}")
    return result


def _review_case_with_ai(text: str, case: dict[str, Any],
                         errors: list[str] | None = None) -> tuple[str | None, dict[str, Any] | None]:
    if deepseek.is_enabled():
        try:
            return "deepseek", deepseek.review_text(text, case)
        except Exception as exc:  # noqa: BLE001
            if errors is not None:
                errors.append(f"DeepSeek 复核失败：{str(exc)[:160]}")
    if qwen.is_enabled():
        try:
            return "qwen", qwen.review_text(text, case)
        except Exception as exc:  # noqa: BLE001
            if errors is not None:
                errors.append(f"Qwen 复核失败：{str(exc)[:160]}")
    return None, None


def _analyze_text_with_case(text: str, errors: list[str] | None = None,
                            skip_ai: bool = False, force_ai: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Guardian-AI 分层过滤：

    1. 短 TTL 缓存直接返回；
    2. 案例库精确/相似命中复用案例；
    3. 本地关键词 + 五维加权评分，明显高风险/明显低风险跳过 AI；
    4. 只有模糊文本才调用 DeepSeek 精判。
    """
    normalized = preprocess_text(text)
    mode = "fast" if skip_ai else ("full-force" if force_ai else "full")
    cache_key = hashlib.sha256((mode + ":" + normalized).encode("utf-8")).hexdigest()
    cached_bundle = result_cache.text_cache.get(cache_key)
    if cached_bundle:
        cached_result = cached_bundle.get("result", {})
        cached_result["cache_hit"] = True
        return cached_result, cached_bundle.get("match", {"hit": False})

    match = case_matcher.lookup(text)
    semantic = 0.0
    if match.get("hit"):
        semantic = float(match.get("similarity") or 0)
    elif match.get("nearest"):
        semantic = float(match["nearest"].get("similarity") or 0)

    if match.get("hit"):
        case = match["case"]
        if match.get("exact"):
            cached_review = case_matcher.result_from_cached_review(case, match)
            if cached_review:
                guardian.compute(text, cached_review, semantic)
                cached_review["engine"] = {
                    "name": "guardian-database-cached-review",
                    "ai": True,
                    "provider": "database",
                    "note": "Guardian-AI 数据库命中 · 复用 AI 复核缓存",
                }
                result_cache.text_cache.set(cache_key, {"result": cached_review, "match": match})
                return cached_review, match

        result = case_matcher.result_from_case(case, match)
        guardian.compute(text, result, semantic)
        if skip_ai:
            result["engine"] = {
                "name": "guardian-database-fast",
                "ai": False,
                "provider": "database",
                "note": "Guardian-AI 数据库命中 · 快速预判",
            }
            result_cache.text_cache.set(cache_key, {"result": result, "match": match})
            return result, match

        provider, review = _review_case_with_ai(text, case, errors)
        if review:
            result = _apply_ai(result, review, source="database", provider=provider)
            guardian.compute(text, result, semantic)
            label = "DeepSeek V4.1" if provider == "deepseek" else "Qwen"
            result["engine"] = {
                "name": f"guardian-database-{provider}",
                "ai": True,
                "provider": provider,
                "note": f"Guardian-AI 数据库命中 + {label} 复核",
            }
            result["match"]["reviewed_by_ai"] = True
            result["match"]["review_provider"] = provider
            result["match"]["review_confidence"] = review.get("confidence")
            result["match"]["review_verdict"] = "confirmed" if review.get("confirmed") else "not_confirmed"
            if not review.get("confirmed"):
                result["match"]["review_note"] = "AI 复核认为与案例不完全一致，建议结合原文判断"
            if match.get("exact"):
                case_matcher.save_review(case["id"], result)
        else:
            result["engine"] = {
                "name": "guardian-database-rule",
                "ai": False,
                "provider": "database",
                "note": "Guardian-AI 数据库命中；AI 复核不可用",
            }
        result_cache.text_cache.set(cache_key, {"result": result, "match": match})
        return result, match

    result = analyzer.analyze_text(text)
    guardian.compute(text, result, semantic)
    result["match"] = {
        "hit": False,
        "nearest": match.get("nearest"),
        "reviewed_by_ai": False,
        "review_provider": None,
    }

    if skip_ai or (guardian.is_decisive(result) and not force_ai):
        result["engine"] = {
            "name": "guardian-rule",
            "ai": False,
            "provider": "rule",
            "note": "Guardian-AI 关键词/规则高置信判定，已跳过 AI",
        }
        reason = "fast_preview" if skip_ai else ("high_confidence" if result.get("risk_score", 0) >= 50 else "obvious_low_risk")
        result["layered"] = {"ai_used": False, "reason": reason}
        result_cache.text_cache.set(cache_key, {"result": result, "match": match})
        return result, match

    result = _enhance_text_with_ai(result, text, errors)
    guardian.compute(text, result, semantic)
    result["layered"] = {"ai_used": True, "reason": "ambiguous_text"}
    result["engine"]["name"] = "guardian-ai"
    result["engine"]["note"] = result["engine"].get("note", "Guardian-AI 语义精判")
    result_cache.text_cache.set(cache_key, {"result": result, "match": match})
    return result, match


def _refine_monitor(payload: MonitorAnalyzeRequest) -> None:
    """后台 AI 二次审查：基于累积上下文，以 AI 确认值为最终风险值。

    流程：先把当前 OCR 文本合并入库（保留对方所有历史消息）→ 取完整累积
    文本 → AI 复审 → 更新库存 AI 最终结果 → 推送可疑片段到 Web。
    """
    try:
        contact = (payload.window or "").strip()
        if not contact or contact in GENERIC_CONTACT_NAMES:
            return
        # 1. 先把当前 OCR 文本合并入库（save 内部按行去重，保留全部历史）
        fast_result, _ = _analyze_text_with_case(payload.text, skip_ai=True)
        conversation_store.save(
            contact_id=contact,
            contact_name=contact,
            window_title=contact,
            text=payload.text,
            result=fast_result,
        )
        # 2. 取合并后的完整累积文本供 AI 阅读上下文
        full_text = conversation_store.get_full_text(contact)
        # 3. AI 基于完整累积上下文复审（force_ai=True 强制精判）
        result, match = _analyze_text_with_case(full_text, skip_ai=False, force_ai=True)
        result = analyzer.build_hit_contract(result, full_text)
        result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        result["match"] = match
        time.sleep(0.8)
        # 4. 更新库存 AI 最终结果（text 保持完整累积文本，全量入库无门槛）
        conversation_store.save(
            contact_id=contact,
            contact_name=contact,
            window_title=contact,
            text=full_text,
            result=result,
        )
        # 5. Web 只展示可疑片段，不全显原文（隐私保护）
        snippets = analyzer.extract_suspicious_snippets(full_text, result)
        monitor_state.publish(
            text=snippets,
            result=result,
            source="tray-ai",
            window=contact,
        )
    except Exception:  # noqa: BLE001
        pass


@app.post("/api/monitor/contact")
def api_monitor_contact(payload: MonitorContactRequest) -> dict[str, Any]:
    if not deepseek.is_enabled():
        raise HTTPException(status_code=503, detail="视觉联系人识别暂不可用")
    try:
        image = base64.b64decode(payload.image_base64, validate=True)
        text = deepseek.read_contact_name(image, payload.mime or "image/png")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"联系人识别失败：{str(exc)[:160]}") from exc
    return {"ok": True, "text": text}


@app.post("/api/monitor/layout")
def api_monitor_layout(payload: MonitorLayoutRequest) -> dict[str, Any]:
    """视觉模型识别聊天主区域；用于 QQ/微信窗口变化后的动态裁剪。"""
    if not deepseek.is_enabled():
        raise HTTPException(status_code=503, detail="视觉布局识别暂不可用")
    try:
        image = base64.b64decode(payload.image_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="图片数据无效") from exc
    try:
        layout = deepseek.analyze_chat_layout(image, payload.mime or "image/png")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"布局识别失败：{str(exc)[:160]}") from exc
    return {"ok": True, "layout": layout}


@app.post("/api/monitor/analyze")
def api_monitor_analyze(payload: MonitorAnalyzeRequest, background: BackgroundTasks) -> dict[str, Any]:
    """托盘自动检测：先数据库/本地规则给可能性，再后台 AI 二次审查。"""
    result, match = _analyze_text_with_case(payload.text, skip_ai=True)
    result = analyzer.build_hit_contract(result, payload.text)
    result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    result["match"] = match
    # 先不推 Web：由托盘收到结果、先弹本机告警，再主动 publish 到 Web。
    background.add_task(_refine_monitor, payload)
    return {"ok": True, "analysis": result, "item": None}


@app.post("/api/monitor/publish")
def api_monitor_publish(payload: MonitorPublishRequest) -> dict[str, Any]:
    # Web 只展示可疑片段，不全显原文（隐私保护）
    snippets = analyzer.extract_suspicious_snippets(payload.text, payload.result)
    item = monitor_state.publish(
        text=snippets,
        result=payload.result,
        source=payload.source,
        window=payload.window,
    )
    return {"ok": True, "item": item}


@app.get("/api/monitor/latest")
def api_monitor_latest() -> dict[str, Any]:
    return {"ok": True, "item": monitor_state.latest()}


@app.post("/api/analyze/preview")
def analyze_preview(payload: TextAnalyzeRequest) -> dict[str, Any]:
    """Web 快速预判：只跑本地规则，不写库、不调外部模型。"""
    result = analyzer.analyze_text(payload.text)
    result = analyzer.build_hit_contract(result, payload.text)
    result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return {"ok": True, "analysis": result}


@app.post("/api/analyze/text")
def analyze_text_endpoint(payload: TextAnalyzeRequest) -> dict[str, Any]:
    started = time.perf_counter()
    result, match = _analyze_text_with_case(payload.text, skip_ai=False)
    result = analyzer.build_hit_contract(result, payload.text)
    result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    analysis_id = None
    if payload.save and payload.text.strip():
        try:
            duration = int((time.perf_counter() - started) * 1000)
            analysis_id = repository.save_analysis(
                source="text",
                input_text=payload.text,
                note=None,
                result=result,
                duration_ms=duration,
            )
            result["id"] = analysis_id
            content_store.record_staging(
                user_key=payload.client_id,
                modality="text",
                raw_text=payload.text,
                analysis_id=analysis_id,
                result=result,
            )
            added = False
            if not match.get("hit"):
                added = case_matcher.add_case_from_result(payload.text, result)
                if added:
                    result["match"]["stored_as_case"] = True
            matched = "数据库命中" if match.get("hit") else "数据库未命中"
            _log_safe(
                level="warning" if result["risk_level"] in {"high", "critical"} else "info",
                event="analyze",
                message=f"文本检测完成：{result['risk_label']} {result['risk_score']} 分（{matched}{'，已收录新案例' if added else ''}）",
                meta={
                    "analysis_id": analysis_id,
                    "risk_score": result["risk_score"],
                    "source": "text",
                    "match": match.get("hit", False),
                    "case_id": (match.get("case") or {}).get("id"),
                    "stored_as_case": added,
                },
                duration_ms=duration,
            )
        except Exception as exc:  # noqa: BLE001
            _log_safe(level="error", event="storage", message=f"保存文本分析失败：{exc}")
            raise HTTPException(status_code=500, detail=f"保存分析结果失败：{exc}") from exc
    return {"ok": True, "analysis": result, "id": analysis_id, "saved": bool(analysis_id)}


# --------------------------------------------------------------------------
# 多模态分析（文本 + 图片 + 语音）
# --------------------------------------------------------------------------
async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"文件 {file.filename} 超过大小限制")
    if not data:
        raise HTTPException(status_code=400, detail=f"文件 {file.filename} 为空")
    return data


def _save_upload(data: bytes, original_name: str, kind: str) -> tuple[str, str]:
    ext = Path(original_name or "").suffix.lower()
    if not ext:
        ext = ".jpg" if kind == "image" else ".webm"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = config.UPLOAD_DIR / stored_name
    target.write_bytes(data)
    return stored_name, ext


def _image_meta(data: bytes, file: UploadFile) -> tuple[int | None, int | None, str | None]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            thumb = image.copy()
            thumb.thumbnail((480, 480))
            if thumb.mode not in ("RGB", "RGBA"):
                thumb = thumb.convert("RGB")
            thumb_name = f"{uuid.uuid4().hex}.jpg"
            if thumb.mode == "RGBA":
                background = Image.new("RGB", thumb.size, (255, 255, 255))
                background.paste(thumb, mask=thumb.split()[-1])
                thumb = background
            thumb.save(config.THUMB_DIR / thumb_name, format="JPEG", quality=86)
            return width, height, thumb_name
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"图片 {file.filename} 无法解析：{exc}") from exc


async def _safe_ocr(path) -> str:
    try:
        return await asyncio.to_thread(ocr.extract_text, path)
    except Exception:  # noqa: BLE001
        return ""


async def _process_image_upload(file: UploadFile, note: str, save: bool) -> dict[str, Any]:
    original_name = Path(file.filename or "").name
    ext = Path(original_name).suffix.lower()
    content_type = file.content_type or mimetypes.guess_type(original_name)[0] or ""
    if ext not in config.IMAGE_EXTENSIONS:
        return {"error": f"{original_name}：不是支持的图片格式"}
    try:
        data = await _read_upload(file, config.MAX_IMAGE_MB * 1024 * 1024)
        width, height, thumb_name = _image_meta(data, file)
    except HTTPException as exc:
        return {"error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{original_name}：图片处理失败 {str(exc)[:120]}"}

    stored_name, _ = _save_upload(data, original_name, "image")
    sha256 = hashlib.sha256(data).hexdigest()
    image_text = ""
    ai_data: dict[str, Any] = {}
    ai_provider = ""
    ai_error = ""
    ocr_error = ""
    ocr_source = ""
    image_cached = content_store.lookup_image(sha256)
    if image_cached:
        local = dict(image_cached.get("result") or {})
        local["engine"] = {
            "name": "database-image-cache",
            "ai": False,
            "provider": "database",
            "note": "图片库命中 · 复用缓存视觉结果",
        }
        local["image_match"] = {
            "hit": True,
            "case_id": image_cached["id"],
            "sha256": sha256,
            "cached": True,
        }
        image_text = str(image_cached.get("ocr_text") or "")
        ai_provider = "database"
        ocr_source = "image-cache"
    else:
        # OCR 与视觉模型同时跑，最终只等最慢的一路，不串行阻塞。
        ocr_task = asyncio.create_task(_safe_ocr(config.UPLOAD_DIR / stored_name)) if ocr.is_available() else None
        if deepseek.is_enabled():
            try:
                ai_data = await asyncio.to_thread(
                    deepseek.analyze_image, data, content_type or "image/jpeg"
                )
                image_text = str(ai_data.get("ocr_text") or "")
                ai_provider = "deepseek"
                ocr_source = "deepseek-vl"
            except Exception as exc:  # noqa: BLE001
                ai_error = str(exc)
        if not ai_data and qwen.is_enabled():
            try:
                ai_data = await asyncio.to_thread(qwen.analyze_image, data, content_type or "image/jpeg")
                image_text = str(ai_data.get("ocr_text") or "")
                ai_provider = "qwen"
                ocr_source = "qwen-vl"
            except Exception as exc:  # noqa: BLE001
                ai_error = str(exc)
        if ocr_task:
            if not image_text:
                image_text = await ocr_task
                if image_text:
                    ocr_source = "windows-ocr"
            else:
                ocr_task.cancel()
        local = analyzer.analyze_text("\n".join([note, original_name, image_text]).strip())
        local = _apply_ai(local, ai_data, source="image", provider=ai_provider) if ai_data else local
        if ai_provider == "deepseek":
            local["engine"]["note"] = "Guardian-AI · DeepSeek V4.1 视觉"
        elif ai_provider == "qwen":
            local["engine"]["note"] = "Guardian-AI · Qwen-VL 视觉"
        elif image_text:
            local["engine"]["note"] = "Guardian-AI · Windows OCR + 本地规则"
        elif not (deepseek.is_enabled() or qwen.is_enabled()):
            local["engine"]["note"] = "Guardian-AI · 未配置视觉模型且 OCR 未识别到文字"
        elif ai_error:
            local["engine"]["note"] = f"Guardian-AI · 视觉调用失败，已降级：{ai_error[:120]}"

    if save:
        try:
            content_store.record_image_case(
                sha256=sha256,
                original_name=original_name,
                stored_name=stored_name,
                content_type=content_type,
                size_bytes=len(data),
                width=width,
                height=height,
                ocr_text=image_text,
                result=local,
            )
        except Exception:  # noqa: BLE001 - 并发同图可能触发唯一键冲突
            pass

    part = {
        "type": "image",
        "filename": original_name,
        "result": local,
        "text": image_text or note,
        "extra": {
            "width": width,
            "height": height,
            "ocr_text": image_text,
            "ocr_source": ocr_source,
            "ai_provider": ai_provider,
            "image_cached": bool(image_cached),
            "ai_error": ai_error,
            "ocr_error": ocr_error,
            "chars": len(image_text),
        },
    }
    media = {
        "original_name": original_name,
        "stored_name": stored_name,
        "thumb_name": thumb_name,
        "media_type": "image",
        "content_type": content_type,
        "size_bytes": len(data),
        "width": width,
        "height": height,
        "sha256": sha256,
        "risk_score": local["risk_score"],
        "ocr_text": image_text,
        "detail": {
            "engine": local.get("engine"),
            "ai_error": ai_error,
            "ocr_source": ocr_source,
            "ai_provider": ai_provider,
        },
    }
    staging = None
    if save:
        staging = {
            "modality": "image",
            "stored_name": stored_name,
            "original_name": original_name,
            "content_type": content_type,
            "size_bytes": len(data),
            "width": width,
            "height": height,
            "sha256": sha256,
            "ocr_text": image_text,
            "raw_text": note,
        }
    return {"part": part, "media": media, "staging": staging}


async def _process_audio_upload(file: UploadFile, note: str, save: bool) -> dict[str, Any]:
    original_name = Path(file.filename or "").name
    ext = Path(original_name).suffix.lower()
    content_type = file.content_type or mimetypes.guess_type(original_name)[0] or ""
    if not (ext in config.AUDIO_EXTENSIONS or content_type.startswith("audio/")):
        return {"error": f"{original_name}：不是支持的音频格式"}
    try:
        data = await _read_upload(file, config.MAX_AUDIO_MB * 1024 * 1024)
    except HTTPException as exc:
        return {"error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{original_name}：音频读取失败 {str(exc)[:120]}"}

    stored_name, _ = _save_upload(data, original_name, "audio")
    sha256 = hashlib.sha256(data).hexdigest()
    transcript = ""
    ai_error = ""
    if qwen.is_enabled():
        try:
            transcript = await asyncio.to_thread(qwen.transcribe_audio, data, content_type or "audio/webm")
        except Exception as exc:  # noqa: BLE001
            ai_error = str(exc)
    local = analyzer.analyze_text("\n".join([note, transcript]).strip())
    if transcript:
        local["engine"] = {
            "name": "hybrid-qwen-rule",
            "ai": True,
            "provider": "qwen",
            "source": "audio",
            "note": "Qwen-ASR 语音转写 + 本地规则引擎",
        }
    else:
        local["engine"]["note"] = (
            f"Qwen-ASR 调用失败：{ai_error[:120]}" if ai_error
            else "DeepSeek V4.1 Flash 仅支持文本+图像；语音请配置 QWEN_API_KEY，或手动补充转写文本"
        )
    if save and transcript:
        try:
            case_matcher.add_case_from_result(transcript, local, source="audio")
        except Exception:  # noqa: BLE001
            pass

    part = {
        "type": "audio",
        "filename": original_name,
        "result": local,
        "text": transcript or note,
        "extra": {"transcript": transcript, "ai_error": ai_error, "chars": len(transcript)},
    }
    media = {
        "original_name": original_name,
        "stored_name": stored_name,
        "thumb_name": None,
        "media_type": "audio",
        "content_type": content_type,
        "size_bytes": len(data),
        "width": None,
        "height": None,
        "sha256": sha256,
        "risk_score": local["risk_score"],
        "ocr_text": transcript,
        "detail": {"engine": local.get("engine"), "ai_error": ai_error},
    }
    staging = None
    if save:
        staging = {
            "modality": "audio",
            "stored_name": stored_name,
            "original_name": original_name,
            "content_type": content_type,
            "size_bytes": len(data),
            "sha256": sha256,
            "transcript": transcript,
            "raw_text": note,
        }
    return {"part": part, "media": media, "staging": staging}


def _apply_ai(result: dict[str, Any], ai_data: dict[str, Any], *, source: str,
              provider: str = "qwen") -> dict[str, Any]:
    """将 AI 结果叠加到本地规则结果上（保留可解释性，取较高风险）。"""
    if not ai_data:
        return result
    ai_score = 0
    try:
        ai_score = max(0, min(100, int(ai_data.get("risk_score", 0))))
    except (TypeError, ValueError):
        ai_score = 0
    evidence = ai_common.signals_to_evidence(ai_data, provider)
    known = {item.get("label") for item in result.get("signals", [])}
    for item in evidence:
        if item["label"] not in known:
            result["signals"].append(item)
            known.add(item["label"])

    ai_dims = {key: 0 for key in analyzer.DIMENSIONS}
    for item in evidence:
        ai_dims[item["dim"]] = ai_dims.get(item["dim"], 0) + item["weight"]
    dims = {item["key"]: item["score"] for item in result["dimensions"]}
    for key, meta in analyzer.DIMENSIONS.items():
        dims[key] = max(dims.get(key, 0), min(meta["max"], ai_dims.get(key, 0)))

    local_score = int(result.get("risk_score", 0))
    blended = int(round(local_score * 0.55 + ai_score * 0.45))
    if ai_score >= 70:
        blended = max(blended, ai_score)
    score = max(blended, min(100, sum(dims.values())))
    score = max(0, min(100, score))
    level = analyzer._level_for(score)
    result["risk_score"] = score
    result["risk_level"] = level
    result["risk_label"] = analyzer.LEVELS[level]["label"]
    result["risk_hint"] = analyzer.LEVELS[level]["hint"]
    result["dimensions"] = analyzer._dimension_payload(dims)
    if ai_data.get("scam_type") and (local_score < 30 or not result.get("scam_type")):
        result["scam_type"] = str(ai_data["scam_type"])[:64]
    if ai_data.get("summary") and (ai_score >= local_score or "暂未发现" in result.get("summary", "")):
        result["summary"] = str(ai_data["summary"])[:500]
    for suggestion in ai_data.get("suggestions") or []:
        text = str(suggestion)[:200]
        if text and text not in result["suggestions"]:
            result["suggestions"].append(text)
    result["suggestions"] = result["suggestions"][:8]
    provider_label = "DeepSeek V4.1" if provider == "deepseek" else "Qwen"
    result["engine"] = {
        "name": f"guardian-{provider}",
        "ai": True,
        "provider": provider,
        "source": source,
        "note": f"Guardian-AI · {provider_label} + 本地规则引擎",
    }
    result["ai"] = {"provider": provider, "score": ai_score, "enabled": True}
    return result


@app.post("/api/analyze")
async def analyze_multimodal(
    text: str = Form(""),
    note: str = Form(""),
    save: bool = Form(True),
    client_id: str = Form("anonymous"),
    files: list[UploadFile] | None = File(None),
) -> dict[str, Any]:
    started = time.perf_counter()
    text = (text or "")[:20000]
    note = (note or "")[:500]
    errors: list[str] = []
    text_task = asyncio.create_task(asyncio.to_thread(_analyze_text_with_case, text, errors))
    parts: list[dict[str, Any]] = []
    media_rows: list[dict[str, Any]] = []
    staging_rows: list[dict[str, Any]] = []
    if text.strip():
        staging_rows.append({"modality": "text", "raw_text": text})

    image_upload_files: list[UploadFile] = []
    audio_upload_files: list[UploadFile] = []
    for file in files or []:
        if not file.filename:
            continue
        original_name = Path(file.filename).name
        ext = Path(original_name).suffix.lower()
        content_type = file.content_type or mimetypes.guess_type(original_name)[0] or ""
        if ext in config.IMAGE_EXTENSIONS:
            image_upload_files.append(file)
        elif ext in config.AUDIO_EXTENSIONS or content_type.startswith("audio/"):
            audio_upload_files.append(file)
        else:
            errors.append(f"{original_name}：不支持的文件类型")

    tasks = []
    tasks.extend(asyncio.create_task(_process_image_upload(file, note, save)) for file in image_upload_files)
    tasks.extend(asyncio.create_task(_process_audio_upload(file, note, save)) for file in audio_upload_files)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    base, text_match = await text_task
    text_case_result = copy.deepcopy(base)
    for result in results:
        if isinstance(result, Exception):
            errors.append(f"文件处理失败：{str(result)[:160]}")
            continue
        if not isinstance(result, dict) or result.get("error"):
            errors.append(str((result or {}).get("error", "文件处理失败")))
            continue
        if result.get("part"):
            parts.append(result["part"])
        if result.get("media"):
            media_rows.append(result["media"])
        if result.get("staging"):
            staging_rows.append(result["staging"])
    image_parts = [item for item in parts if item.get("type") == "image"]

    combined = analyzer.merge_modalities(base, parts)
    guardian_text = "\n".join(
        [text, note] + [str(part.get("text", "")) for part in parts if part.get("text")]
    ).strip()
    semantic = 0.0
    if text_match.get("hit"):
        semantic = float(text_match.get("similarity") or 0)
    elif text_match.get("nearest"):
        semantic = float(text_match["nearest"].get("similarity") or 0)
    combined = guardian.compute(guardian_text, combined, semantic)

    # 多图联合分析：不是简单取单图最高分，而是让模型横向比对多张图片的信息。
    if len(image_parts) >= 2:
        cross_image: dict[str, Any] = {
            "count": len(image_parts),
            "enabled": deepseek.is_enabled(),
            "summary": "",
            "relationships": [],
            "image_findings": [],
        }
        if deepseek.is_enabled():
            image_briefs = []
            for index, part in enumerate(image_parts, start=1):
                image_briefs.append({
                    "index": index,
                    "filename": part.get("filename"),
                    "risk_score": part.get("result", {}).get("risk_score", 0),
                    "summary": part.get("result", {}).get("summary", ""),
                    "ocr_text": str(part.get("extra", {}).get("ocr_text", ""))[:3000],
                    "signals": [
                        item.get("label")
                        for item in part.get("result", {}).get("signals", [])
                        if not item.get("protective")
                    ][:8],
                })
            try:
                cross_data = await asyncio.to_thread(
                    deepseek.analyze_image_group, text, note, image_briefs
                )
                combined = _apply_ai(combined, cross_data, source="multi_image", provider="deepseek")
                combined["engine"] = {
                    "name": "hybrid-deepseek-multi-image",
                    "ai": True,
                    "provider": "deepseek",
                    "note": "DeepSeek V4.1 多图联合分析 + 本地规则引擎",
                }
                cross_image.update({
                    "summary": str(cross_data.get("summary", "")),
                    "relationships": cross_data.get("relationships") or [],
                    "image_findings": cross_data.get("image_findings") or [],
                    "risk_score": cross_data.get("risk_score"),
                    "scam_type": cross_data.get("scam_type"),
                })
            except Exception as exc:  # noqa: BLE001
                cross_image["error"] = str(exc)[:200]
                errors.append(f"多图联合分析失败：{str(exc)[:160]}")
        else:
            cross_image["summary"] = "未启用视觉模型，已完成多图并行单图分析"
        combined["cross_image"] = cross_image

    combined = analyzer.build_hit_contract(combined, text or note)
    combined["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    combined["modality_errors"] = errors
    source = _source_for(parts, bool(text.strip()))
    analysis_id = None
    if save and (text.strip() or note.strip() or parts):
        try:
            duration = int((time.perf_counter() - started) * 1000)
            analysis_id = repository.save_analysis(
                source=source,
                input_text=text,
                note=note or None,
                result=combined,
                images=media_rows,
                duration_ms=duration,
            )
            combined["id"] = analysis_id
            for row in staging_rows:
                content_store.record_staging(
                    user_key=client_id,
                    analysis_id=analysis_id,
                    result=combined,
                    **row,
                )
            added = False
            if text.strip() and not text_match.get("hit"):
                added = case_matcher.add_case_from_result(text, text_case_result)
                if added:
                    combined.setdefault("match", {})["stored_as_case"] = True
            _log_safe(
                level="warning" if combined["risk_level"] in {"high", "critical"} else "info",
                event="analyze",
                message=f"多模态检测完成：{combined['risk_label']} {combined['risk_score']} 分（{source}，"
                        f"{'数据库命中' if text_match.get('hit') else '数据库未命中'}"
                        f"{'，已收录新案例' if added else ''}）",
                meta={
                    "analysis_id": analysis_id,
                    "risk_score": combined["risk_score"],
                    "source": source,
                    "match": text_match.get("hit", False),
                    "case_id": (text_match.get("case") or {}).get("id"),
                    "stored_as_case": added,
                    "files": [row["original_name"] for row in media_rows],
                },
                duration_ms=duration,
            )
        except Exception as exc:  # noqa: BLE001
            _log_safe(level="error", event="storage", message=f"保存多模态分析失败：{exc}")
            raise HTTPException(status_code=500, detail=f"保存分析结果失败：{exc}") from exc
    return {"ok": True, "analysis": combined, "id": analysis_id, "saved": bool(analysis_id), "errors": errors}


# --------------------------------------------------------------------------
# 历史记录
# --------------------------------------------------------------------------
@app.get("/api/history")
def api_history(
    page: int = Query(1, ge=1),
    size: int = Query(12, ge=1, le=50),
    keyword: str = "",
    level: str = "",
    source: str = "",
    deleted: bool = False,
) -> dict[str, Any]:
    try:
        return {"ok": True, **repository.list_analyses(
            page=page, size=size, keyword=keyword.strip(), level=level, source=source,
            deleted_only=deleted,
        )}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取历史记录失败：{exc}") from exc


@app.get("/api/history/{analysis_id}")
def api_history_detail(analysis_id: int) -> dict[str, Any]:
    analysis = repository.get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="记录不存在")
    analysis["reports"] = repository.list_reports(analysis_id)
    return {"ok": True, "analysis": analysis}


@app.delete("/api/history/{analysis_id}")
def api_history_delete(analysis_id: int) -> dict[str, Any]:
    if not repository.delete_analysis(analysis_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    _log_safe(level="info", event="delete", message=f"删除分析记录 #{analysis_id}")
    return {"ok": True}


@app.post("/api/history/{analysis_id}/restore")
def api_history_restore(analysis_id: int) -> dict[str, Any]:
    """从回收站恢复误删的分析记录（软删除，isdeleted=1 → 0）。"""
    if not repository.restore_analysis(analysis_id):
        raise HTTPException(status_code=404, detail="回收站中没有该记录")
    _log_safe(level="info", event="restore", message=f"恢复分析记录 #{analysis_id}")
    return {"ok": True}


@app.post("/api/history/{analysis_id}/feedback")
def api_feedback(analysis_id: int, payload: FeedbackRequest) -> dict[str, Any]:
    if not repository.set_feedback(analysis_id, payload.is_false_positive, payload.note.strip()):
        raise HTTPException(status_code=404, detail="记录不存在")
    _log_safe(
        level="info",
        event="feedback",
        message=("标记为误报" if payload.is_false_positive else "取消误报标记") + f"：#{analysis_id}",
        meta={"analysis_id": analysis_id, "note": payload.note.strip()},
    )
    return {"ok": True}


@app.get("/api/history/{analysis_id}/export")
def api_export(analysis_id: int) -> Response:
    analysis = repository.get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="记录不存在")
    content = json.dumps(analysis, ensure_ascii=False, indent=2)
    filename = f"anti-fraud-analysis-{analysis_id}.json"
    _log_safe(level="info", event="export", message=f"导出证据 JSON：#{analysis_id}")
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/history/{analysis_id}/report.txt")
def api_report_text(analysis_id: int) -> Response:
    analysis = repository.get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="记录不存在")
    content = build_report_text(analysis)
    filename = f"anti-fraud-report-{analysis_id}.txt"
    _log_safe(level="info", event="export", message=f"导出处置报告：#{analysis_id}")
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------
# 举报
# --------------------------------------------------------------------------
@app.post("/api/reports")
def api_create_report(payload: ReportRequest) -> dict[str, Any]:
    analysis = repository.get_analysis(payload.analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    title = f"反诈举报材料 · {analysis.get('scam_type') or '疑似诈骗'}"
    content = build_report_text(analysis)
    if payload.note:
        content += f"\n补充说明：{payload.note}\n"
    report = repository.save_report(
        analysis_id=payload.analysis_id,
        channel=payload.channel,
        title=title,
        content=content,
    )
    _log_safe(
        level="warning",
        event="report",
        message=f"生成举报材料 {report['report_no']}（{payload.channel}）",
        meta={"analysis_id": payload.analysis_id, "report_id": report["id"], "channel": payload.channel},
    )
    return {"ok": True, "report": report, "download_url": f"/api/reports/{report['id']}/download"}


@app.get("/api/reports/{report_id}/download")
def api_download_report(report_id: int) -> Response:
    report = repository.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="举报材料不存在")
    content = f"举报编号：{report['report_no']}\n举报渠道：{report['channel']}\n\n{report['content']}"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report["report_no"]}.txt"'},
    )


# --------------------------------------------------------------------------
# 静态页面
# --------------------------------------------------------------------------
app.mount("/css", StaticFiles(directory=config.FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=config.FRONTEND_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIR / "assets", check_dir=False), name="assets")
def _safe_media_path(directory, filename: str):
    name = Path(filename).name
    path = (directory / name).resolve()
    if directory.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    return path


def _assert_media_owner(filename: str, *, thumbnail: bool = False) -> None:
    """媒体文件也必须按租户隔离，禁止通过猜文件名跨用户读取。"""
    name = Path(filename).name
    user_id = tenant.user_id()
    if thumbnail:
        row = db.query_one(
            "SELECT TOP 1 id FROM dbo.images WHERE thumb_name = ? AND user_id = ? AND isdeleted = 0",
            [name, user_id],
        )
    else:
        row = db.query_one(
            "SELECT TOP 1 id FROM dbo.images WHERE stored_name = ? AND user_id = ? AND isdeleted = 0",
            [name, user_id],
        ) or db.query_one(
            "SELECT TOP 1 id FROM dbo.staging_contents WHERE stored_name = ? AND user_id = ? AND isdeleted = 0",
            [name, user_id],
        )
    if not row:
        raise HTTPException(status_code=404, detail="媒体文件不存在")


@app.get("/api/media/thumbnail/{filename}")
def media_thumbnail(filename: str, _: None = Depends(security.verify_token)):
    _assert_media_owner(filename, thumbnail=True)
    path = _safe_media_path(config.THUMB_DIR, filename)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@app.get("/api/media/original/{filename}")
def media_original(filename: str, _: None = Depends(security.verify_token)):
    _assert_media_owner(filename)
    path = _safe_media_path(config.UPLOAD_DIR, filename)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=path.name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _page_response(filename: str) -> FileResponse:
    response = FileResponse(config.FRONTEND_DIR / "html" / filename)
    security.set_token_cookie(response)
    return response


@app.get("/")
def index_page() -> FileResponse:
    return _page_response("index.html")


@app.get("/index.html")
def index_page_explicit() -> FileResponse:
    return _page_response("index.html")


@app.get("/chat-test.html")
def chat_test_page() -> FileResponse:
    return _page_response("chat-test.html")


@app.get("/chat.html")
def chat_page() -> FileResponse:
    return _page_response("chat.html")


@app.get("/history.html")
def history_page() -> FileResponse:
    return _page_response("history.html")


@app.get("/logs.html")
def logs_page() -> FileResponse:
    return _page_response("logs.html")


@app.exception_handler(404)
def not_found(_: Any, __: Any) -> JSONResponse:
    return JSONResponse(status_code=404, content={"ok": False, "detail": "资源不存在"})
