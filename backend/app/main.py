"""反诈卫士 FastAPI 应用。

启动：
    python backend/run.py
或：
    uvicorn backend.app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import analyzer, config, db, ocr, qwen, repository

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.ensure_database()
        repository.add_log(level="success", event="system", message="反诈卫士服务启动，数据库连接成功")
    except Exception as exc:  # noqa: BLE001 - 启动阶段尽量给出明确提示
        print(f"[反诈卫士] 数据库初始化失败：{exc}")
    yield


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    description="反诈卫士：面向青年的 AI 诈骗识别与个人信息保护助手",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 请求模型
# --------------------------------------------------------------------------
class TextAnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    save: bool = True


class FeedbackRequest(BaseModel):
    is_false_positive: bool = True
    note: str = Field(default="", max_length=500)


class ReportRequest(BaseModel):
    analysis_id: int
    channel: str = Field(default="12321", max_length=32)
    note: str = Field(default="", max_length=500)


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
@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        database = db.health()
    except Exception as exc:  # noqa: BLE001
        database = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "database": database,
        "ai": qwen.status(),
    }


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    return {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "ai": qwen.status(),
        "limits": {
            "max_image_mb": config.MAX_IMAGE_MB,
            "max_audio_mb": config.MAX_AUDIO_MB,
            "max_text": 20000,
        },
    }


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


@app.get("/api/stats")
def api_stats() -> dict[str, Any]:
    try:
        return {"ok": True, **repository.stats()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取统计数据失败：{exc}") from exc


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
def _enhance_text_with_qwen(result: dict[str, Any], text: str, errors: list[str] | None = None) -> dict[str, Any]:
    if not qwen.is_enabled() or not text.strip():
        return result
    try:
        ai_data = qwen.analyze_text(text)
        result = _apply_ai(result, ai_data, source="text")
        result["engine"]["note"] = "Qwen 文本理解 + 本地规则引擎"
    except Exception as exc:  # noqa: BLE001
        result["engine"]["note"] = f"Qwen 文本调用失败，已降级为本地规则：{str(exc)[:120]}"
        if errors is not None:
            errors.append(f"Qwen 文本分析失败：{str(exc)[:160]}")
    return result


@app.post("/api/analyze/text")
def analyze_text_endpoint(payload: TextAnalyzeRequest) -> dict[str, Any]:
    started = time.perf_counter()
    result = analyzer.analyze_text(payload.text)
    result = _enhance_text_with_qwen(result, payload.text)
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
            _log_safe(
                level="warning" if result["risk_level"] in {"high", "critical"} else "info",
                event="analyze",
                message=f"文本检测完成：{result['risk_label']} {result['risk_score']} 分",
                meta={"analysis_id": analysis_id, "risk_score": result["risk_score"], "source": "text"},
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


def _apply_ai(result: dict[str, Any], ai_data: dict[str, Any], *, source: str) -> dict[str, Any]:
    """将 Qwen 结果叠加到本地规则结果上（保留可解释性，取较高风险）。"""
    if not ai_data:
        return result
    ai_score = 0
    try:
        ai_score = max(0, min(100, int(ai_data.get("risk_score", 0))))
    except (TypeError, ValueError):
        ai_score = 0
    evidence = qwen.qwen_signals_to_evidence(ai_data)
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
    result["engine"] = {"name": "hybrid-qwen-rule", "ai": True, "source": source}
    result["ai"] = {"provider": "qwen", "score": ai_score, "enabled": True}
    return result


@app.post("/api/analyze")
async def analyze_multimodal(
    text: str = Form(""),
    note: str = Form(""),
    save: bool = Form(True),
    files: list[UploadFile] | None = File(None),
) -> dict[str, Any]:
    started = time.perf_counter()
    text = (text or "")[:20000]
    note = (note or "")[:500]
    errors: list[str] = []
    base = analyzer.analyze_text(text)
    base = _enhance_text_with_qwen(base, text, errors)
    parts: list[dict[str, Any]] = []
    media_rows: list[dict[str, Any]] = []

    for file in files or []:
        if not file.filename:
            continue
        original_name = Path(file.filename).name
        ext = Path(original_name).suffix.lower()
        content_type = file.content_type or mimetypes.guess_type(original_name)[0] or ""
        is_image = ext in config.IMAGE_EXTENSIONS or content_type.startswith("image/")
        is_audio = ext in config.AUDIO_EXTENSIONS or content_type.startswith("audio/")
        if not is_image and not is_audio:
            errors.append(f"{original_name}：不支持的文件类型")
            continue

        max_bytes = (config.MAX_IMAGE_MB if is_image else config.MAX_AUDIO_MB) * 1024 * 1024
        try:
            data = await _read_upload(file, max_bytes)
        except HTTPException as exc:
            errors.append(str(exc.detail))
            continue
        stored_name, _ = _save_upload(data, original_name, "image" if is_image else "audio")
        sha256 = hashlib.sha256(data).hexdigest()

        if is_image:
            try:
                width, height, thumb_name = _image_meta(data, file)
            except HTTPException as exc:
                errors.append(str(exc.detail))
                continue
            image_text = ""
            ai_data: dict[str, Any] = {}
            ai_error = ""
            ocr_error = ""
            ocr_source = ""
            if qwen.is_enabled():
                try:
                    ai_data = await asyncio.to_thread(qwen.analyze_image, data, content_type or "image/jpeg")
                    image_text = str(ai_data.get("ocr_text") or "")
                    ocr_source = "qwen-vl"
                except Exception as exc:  # noqa: BLE001
                    ai_error = str(exc)
            if not image_text and ocr.is_available():
                try:
                    image_text = await asyncio.to_thread(
                        ocr.extract_text, config.UPLOAD_DIR / stored_name
                    )
                    if image_text:
                        ocr_source = "windows-ocr"
                except Exception as exc:  # noqa: BLE001
                    ocr_error = str(exc)
            local = analyzer.analyze_text("\n".join([note, original_name, image_text]).strip())
            local = _apply_ai(local, ai_data, source="image") if ai_data else local
            if ai_data:
                local["engine"]["note"] = "Qwen-VL 图片理解 + 本地规则引擎"
            elif image_text:
                local["engine"]["note"] = "Windows OCR 识别截图文字 + 本地规则引擎"
            elif not qwen.is_enabled():
                local["engine"]["note"] = "未配置 Qwen-VL 且 OCR 未识别到文字：图片仅完成格式与元数据校验"
            elif ai_error:
                local["engine"]["note"] = f"Qwen-VL 调用失败，已降级为本地规则：{ai_error[:120]}"
            parts.append({
                "type": "image",
                "filename": original_name,
                "result": local,
                "text": image_text or note,
                "extra": {
                    "width": width,
                    "height": height,
                    "ocr_text": image_text,
                    "ocr_source": ocr_source,
                    "ai_error": ai_error,
                    "ocr_error": ocr_error,
                    "chars": len(image_text),
                },
            })
            media_rows.append({
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
                "detail": {"engine": local.get("engine"), "ai_error": ai_error, "ocr_source": ocr_source},
            })
        else:
            transcript = ""
            ai_error = ""
            if qwen.is_enabled():
                try:
                    transcript = await asyncio.to_thread(qwen.transcribe_audio, data, content_type or "audio/webm")
                except Exception as exc:  # noqa: BLE001
                    ai_error = str(exc)
            local = analyzer.analyze_text("\n".join([note, transcript]).strip())
            if transcript:
                local["engine"] = {"name": "hybrid-qwen-rule", "ai": True, "source": "audio"}
            else:
                local["engine"]["note"] = (
                    f"Qwen-ASR 调用失败：{ai_error[:120]}" if ai_error
                    else "未配置 Qwen-ASR：请补充语音转写文本，或配置 QWEN_API_KEY"
                )
            parts.append({
                "type": "audio",
                "filename": original_name,
                "result": local,
                "text": transcript or note,
                "extra": {"transcript": transcript, "ai_error": ai_error, "chars": len(transcript)},
            })
            media_rows.append({
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
            })

    combined = analyzer.merge_modalities(base, parts)
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
            _log_safe(
                level="warning" if combined["risk_level"] in {"high", "critical"} else "info",
                event="analyze",
                message=f"多模态检测完成：{combined['risk_label']} {combined['risk_score']} 分（{source}）",
                meta={
                    "analysis_id": analysis_id,
                    "risk_score": combined["risk_score"],
                    "source": source,
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
) -> dict[str, Any]:
    try:
        return {"ok": True, **repository.list_analyses(
            page=page, size=size, keyword=keyword.strip(), level=level, source=source
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
app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")
app.mount("/thumbnails", StaticFiles(directory=config.THUMB_DIR), name="thumbnails")


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "html" / "index.html")


@app.get("/index.html")
def index_page_explicit() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "html" / "index.html")


@app.get("/history.html")
def history_page() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "html" / "history.html")


@app.get("/logs.html")
def logs_page() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "html" / "logs.html")


@app.exception_handler(404)
def not_found(_: Any, __: Any) -> JSONResponse:
    return JSONResponse(status_code=404, content={"ok": False, "detail": "资源不存在"})
