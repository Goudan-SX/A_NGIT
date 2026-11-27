"""数据库仓储层：把 SQL 细节集中在这里，路由层只关心业务。"""
from __future__ import annotations

import json
import random
from datetime import datetime
from typing import Any

from . import analyzer, db, tenant


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_analysis(*, source: str, input_text: str, note: str | None,
                  result: dict[str, Any], images: list[dict[str, Any]] | None = None,
                  duration_ms: int = 0) -> int:
    engine = (result.get("engine") or {}).get("name", "local-rule-v1")
    user_id = tenant.user_id()
    user_key = tenant.user_key()
    with db.transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.analyses
                (user_id, user_key, source, input_text, note, risk_score, risk_level, scam_type,
                 summary, result_json, engine, duration_ms)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            user_id,
            user_key,
            source,
            input_text or "",
            note,
            int(result.get("risk_score", 0)),
            result.get("risk_level", "low"),
            result.get("scam_type", ""),
            result.get("summary", ""),
            db.json_dumps(result),
            engine,
            int(duration_ms),
        )
        analysis_id = int(cur.fetchone()[0])

        for image in images or []:
            cur.execute(
                """
                INSERT INTO dbo.images
                    (user_id, user_key, analysis_id, original_name, stored_name, thumb_name, media_type,
                     content_type, size_bytes, width, height, sha256, risk_score,
                     ocr_text, detail_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                user_id,
                user_key,
                analysis_id,
                image.get("original_name", ""),
                image.get("stored_name", ""),
                image.get("thumb_name"),
                image.get("media_type", "image"),
                image.get("content_type"),
                int(image.get("size_bytes", 0)),
                image.get("width"),
                image.get("height"),
                image.get("sha256"),
                int(image.get("risk_score", 0)),
                image.get("ocr_text"),
                db.json_dumps(image.get("detail", {})),
            )
    return analysis_id


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    result = _loads(row.pop("result_json", None))
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "risk_score": row["risk_score"],
        "risk_level": row["risk_level"],
        "scam_type": row["scam_type"],
        "summary": row["summary"],
        "engine": row["engine"],
        "duration_ms": row["duration_ms"],
        "is_false_positive": bool(row["is_false_positive"]),
        "report_count": row["report_count"],
        "signal_count": len([item for item in result.get("signals", []) if not item.get("protective")]),
        "pii_count": len(result.get("pii", [])),
        "modalities": result.get("modalities", []),
        "input_preview": (row.get("input_text") or "")[:120],
    }


def list_analyses(*, page: int = 1, size: int = 12, keyword: str = "",
                  level: str = "", source: str = "", deleted_only: bool = False) -> dict[str, Any]:
    page = max(1, page)
    size = max(1, min(50, size))
    where = ["user_id = ?", "isdeleted = 1" if deleted_only else "isdeleted = 0"]
    params: list[Any] = [tenant.user_id()]
    if keyword:
        where.append("(input_text LIKE ? OR summary LIKE ? OR scam_type LIKE ? OR note LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like, like])
    if level in {"low", "medium", "high", "critical"}:
        where.append("risk_level = ?")
        params.append(level)
    if source in {"text", "image", "audio", "mixed"}:
        where.append("source = ?")
        params.append(source)
    condition = " AND ".join(where)

    total_row = db.query_one(f"SELECT COUNT_BIG(*) AS total FROM dbo.analyses WHERE {condition}", params)
    total = int(total_row["total"]) if total_row else 0
    offset = (page - 1) * size
    rows = db.query_all(
        f"""
        SELECT id, created_at, source, input_text, note, risk_score, risk_level,
               scam_type, summary, result_json, engine, duration_ms,
               is_false_positive, report_count
        FROM dbo.analyses
        WHERE {condition}
        ORDER BY id DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """,
        [*params, offset, size],
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
        "items": [_brief(dict(row)) for row in rows],
    }


def get_analysis(analysis_id: int) -> dict[str, Any] | None:
    row = db.query_one(
        """
        SELECT id, created_at, source, input_text, note, risk_score, risk_level,
               scam_type, summary, result_json, engine, duration_ms,
               is_false_positive, feedback_note, report_count
        FROM dbo.analyses WHERE id = ? AND user_id = ? AND isdeleted = 0
        """,
        [analysis_id, tenant.user_id()],
    )
    if not row:
        return None
    result = _loads(row.get("result_json"))
    result.update({
        "id": row["id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "input_text": analyzer.mask_text(row["input_text"] or "", result),
        "note": row["note"],
        "is_false_positive": bool(row["is_false_positive"]),
        "feedback_note": row["feedback_note"],
        "report_count": row["report_count"],
    })
    images = db.query_all(
        """
        SELECT id, original_name, stored_name, thumb_name, media_type, content_type,
               size_bytes, width, height, sha256, risk_score, created_at
        FROM dbo.images WHERE analysis_id = ? AND user_id = ? AND isdeleted = 0 ORDER BY id
        """,
        [analysis_id, tenant.user_id()],
    )
    result["images"] = images
    return result


def delete_analysis(analysis_id: int) -> bool:
    """软删除：写入 isdeleted/deleted_at，可由回收站恢复。"""
    user_id = tenant.user_id()
    with db.transaction() as conn:
        cur = conn.cursor()
        affected = cur.execute(
            """
            UPDATE dbo.analyses
            SET isdeleted = 1, deleted_at = SYSDATETIME()
            WHERE id = ? AND user_id = ? AND isdeleted = 0
            """,
            (analysis_id, user_id),
        ).rowcount
        if affected:
            cur.execute(
                "UPDATE dbo.images SET isdeleted = 1 WHERE analysis_id = ? AND user_id = ?",
                (analysis_id, user_id),
            )
            cur.execute(
                "UPDATE dbo.reports SET isdeleted = 1 WHERE analysis_id = ? AND user_id = ?",
                (analysis_id, user_id),
            )
    return bool(affected)


def restore_analysis(analysis_id: int) -> bool:
    """从回收站恢复一条被软删除的分析记录。"""
    user_id = tenant.user_id()
    with db.transaction() as conn:
        cur = conn.cursor()
        affected = cur.execute(
            """
            UPDATE dbo.analyses
            SET isdeleted = 0, deleted_at = NULL
            WHERE id = ? AND user_id = ? AND isdeleted = 1
            """,
            (analysis_id, user_id),
        ).rowcount
        if affected:
            cur.execute(
                "UPDATE dbo.images SET isdeleted = 0 WHERE analysis_id = ? AND user_id = ?",
                (analysis_id, user_id),
            )
            cur.execute(
                "UPDATE dbo.reports SET isdeleted = 0 WHERE analysis_id = ? AND user_id = ?",
                (analysis_id, user_id),
            )
    return bool(affected)


def set_feedback(analysis_id: int, is_false_positive: bool, note: str = "") -> bool:
    affected = db.execute(
        "UPDATE dbo.analyses SET is_false_positive = ?, feedback_note = ? WHERE id = ? AND user_id = ?",
        [1 if is_false_positive else 0, note, analysis_id, tenant.user_id()],
    )
    return affected > 0


def save_report(*, analysis_id: int, channel: str, title: str, content: str,
                status: str = "submitted") -> dict[str, Any]:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    report_no = f"AF{stamp}{random.randint(100, 999)}"
    user_id = tenant.user_id()
    user_key = tenant.user_key()
    with db.transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.reports
                (user_id, user_key, report_no, analysis_id, channel, title, content, status)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            user_id,
            user_key,
            report_no,
            analysis_id,
            channel,
            title,
            content,
            status,
        )
        report_id = int(cur.fetchone()[0])
        cur.execute(
            "UPDATE dbo.analyses SET report_count = report_count + 1 WHERE id = ? AND user_id = ?",
            (analysis_id, user_id),
        )
    return {
        "id": report_id,
        "report_no": report_no,
        "analysis_id": analysis_id,
        "channel": channel,
        "title": title,
        "content": content,
        "status": status,
        "created_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
    }


def get_report(report_id: int) -> dict[str, Any] | None:
    return db.query_one(
        """
        SELECT id, report_no, analysis_id, channel, title, content, status, created_at
        FROM dbo.reports WHERE id = ? AND user_id = ? AND isdeleted = 0
        """,
        [report_id, tenant.user_id()],
    )


def list_reports(analysis_id: int) -> list[dict[str, Any]]:
    return db.query_all(
        """
        SELECT id, report_no, analysis_id, channel, title, status, created_at
        FROM dbo.reports WHERE analysis_id = ? AND user_id = ? AND isdeleted = 0 ORDER BY id DESC
        """,
        [analysis_id, tenant.user_id()],
    )


def add_log(*, level: str, event: str, message: str,
            meta: dict[str, Any] | None = None, duration_ms: int | None = None) -> None:
    db.execute(
        """
        INSERT INTO dbo.logs (user_id, user_key, level, event, message, meta_json, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [tenant.user_id(), tenant.user_key(), level, event, message[:1000],
         db.json_dumps(meta or {}), duration_ms],
    )


def list_logs(*, page: int = 1, size: int = 30, level: str = "", event: str = "") -> dict[str, Any]:
    page = max(1, page)
    size = max(1, min(100, size))
    where = ["user_id = ?", "isdeleted = 0"]
    params: list[Any] = [tenant.user_id()]
    if level in {"info", "success", "warning", "error"}:
        where.append("level = ?")
        params.append(level)
    if event:
        where.append("event = ?")
        params.append(event)
    condition = " AND ".join(where)
    total_row = db.query_one(f"SELECT COUNT_BIG(*) AS total FROM dbo.logs WHERE {condition}", params)
    total = int(total_row["total"]) if total_row else 0
    rows = db.query_all(
        f"""
        SELECT id, created_at, level, event, message, meta_json, duration_ms
        FROM dbo.logs WHERE {condition}
        ORDER BY id DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """,
        [*params, (page - 1) * size, size],
    )
    for row in rows:
        row["meta"] = _loads(row.pop("meta_json", None))
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
        "items": rows,
    }


def log_stats() -> dict[str, Any]:
    user_id = tenant.user_id()
    rows = db.query_all(
        "SELECT level, COUNT_BIG(*) AS count FROM dbo.logs WHERE user_id = ? AND isdeleted = 0 GROUP BY level",
        [user_id],
    )
    total_row = db.query_one(
        "SELECT COUNT_BIG(*) AS total FROM dbo.logs WHERE user_id = ? AND isdeleted = 0",
        [user_id],
    ) or {}
    counts = {row["level"]: int(row["count"]) for row in rows}
    return {
        "total": int(total_row.get("total") or 0),
        "levels": {
            "info": counts.get("info", 0),
            "success": counts.get("success", 0),
            "warning": counts.get("warning", 0),
            "error": counts.get("error", 0),
        },
    }


def stats() -> dict[str, Any]:
    user_id = tenant.user_id()
    overview = db.query_one(
        """
        SELECT
            COUNT_BIG(*) AS total,
            SUM(CASE WHEN risk_level IN ('high', 'critical') THEN 1 ELSE 0 END) AS high_risk,
            SUM(CASE WHEN is_false_positive = 1 THEN 1 ELSE 0 END) AS false_positive,
            SUM(CASE WHEN CAST(created_at AS DATE) = CAST(SYSDATETIME() AS DATE) THEN 1 ELSE 0 END) AS today
        FROM dbo.analyses
        WHERE user_id = ? AND isdeleted = 0
        """,
        [user_id],
    ) or {}
    levels = db.query_all(
        "SELECT risk_level AS level, COUNT_BIG(*) AS count FROM dbo.analyses WHERE user_id = ? AND isdeleted = 0 GROUP BY risk_level",
        [user_id],
    )
    sources = db.query_all(
        "SELECT source, COUNT_BIG(*) AS count FROM dbo.analyses WHERE user_id = ? AND isdeleted = 0 GROUP BY source",
        [user_id],
    )
    pii_row = db.query_one(
        """
        SELECT COUNT_BIG(*) AS count FROM dbo.analyses
        WHERE user_id = ? AND isdeleted = 0
          AND ISJSON(result_json) = 1 AND JSON_QUERY(result_json, '$.pii') <> '[]'
        """,
        [user_id],
    ) or {}
    reports = db.query_one(
        "SELECT COUNT_BIG(*) AS count FROM dbo.reports WHERE user_id = ? AND isdeleted = 0",
        [user_id],
    ) or {}
    trend = db.query_all(
        """
        SELECT CONVERT(varchar(10), created_at, 120) AS day,
               COUNT_BIG(*) AS count,
               SUM(CASE WHEN risk_level IN ('high', 'critical') THEN 1 ELSE 0 END) AS high
        FROM dbo.analyses
        WHERE user_id = ? AND isdeleted = 0
          AND created_at >= DATEADD(day, -6, CAST(SYSDATETIME() AS DATE))
        GROUP BY CONVERT(varchar(10), created_at, 120)
        ORDER BY day
        """,
        [user_id],
    )
    return {
        "total": int(overview.get("total") or 0),
        "high_risk": int(overview.get("high_risk") or 0),
        "false_positive": int(overview.get("false_positive") or 0),
        "today": int(overview.get("today") or 0),
        "pii_exposed": int(pii_row.get("count") or 0),
        "reports": int(reports.get("count") or 0),
        "levels": {row["level"]: int(row["count"]) for row in levels},
        "sources": {row["source"]: int(row["count"]) for row in sources},
        "trend": [{"day": row["day"], "count": int(row["count"]), "high": int(row["high"] or 0)} for row in trend],
    }


def list_knowledge() -> list[dict[str, Any]]:
    return db.query_all(
        """
        SELECT id, category, title, content, tags, sort_order
        FROM dbo.knowledge ORDER BY sort_order, id
        """
    )