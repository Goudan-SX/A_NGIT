"""当前用户暂存库 + 图片案例库的数据访问。"""
from __future__ import annotations

import json
from typing import Any

from . import analyzer, config, db, tenant


def _risk(result: dict[str, Any] | None) -> tuple[int | None, str | None]:
    if not result:
        return None, None
    return int(result.get("risk_score", 0)), result.get("risk_level")


def record_staging(*, user_key: str | None = None, modality: str, raw_text: str | None = None,
                   stored_name: str | None = None, original_name: str | None = None,
                   content_type: str | None = None, size_bytes: int | None = None,
                   width: int | None = None, height: int | None = None,
                   sha256: str | None = None, ocr_text: str | None = None,
                   transcript: str | None = None, analysis_id: int | None = None,
                   result: dict[str, Any] | None = None, status: str = "analyzed") -> int:
    risk_score, risk_level = _risk(result)
    safe_text = analyzer.mask_text(raw_text, result) if raw_text else raw_text
    return db.execute(
        """
        INSERT INTO dbo.staging_contents
            (user_id, user_key, client_id, modality, raw_text, stored_name, original_name,
             content_type, size_bytes, width, height, sha256, ocr_text, transcript,
             analysis_id, risk_score, risk_level, status, expires_at)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                DATEADD(day, ?, SYSDATETIME()))
        """,
        [
            tenant.user_id(),
            tenant.user_key(),
            (user_key or "")[:64] or None,
            modality,
            safe_text,
            stored_name,
            original_name,
            content_type,
            size_bytes,
            width,
            height,
            sha256,
            ocr_text,
            transcript,
            analysis_id,
            risk_score,
            risk_level,
            status,
            int(config.STAGING_TTL_DAYS),
        ],
        fetch_identity=True,
    )


def record_image_case(*, sha256: str, original_name: str, stored_name: str,
                      content_type: str | None, size_bytes: int,
                      width: int | None, height: int | None,
                      ocr_text: str | None, result: dict[str, Any]) -> int:
    user_id = tenant.user_id()
    existing = db.query_one(
        "SELECT id FROM dbo.image_cases WHERE sha256 = ? AND user_id = ? AND isdeleted = 0",
        [sha256, user_id],
    )
    if existing:
        db.execute(
            "UPDATE dbo.image_cases SET hit_count = hit_count + 1, updated_at = SYSDATETIME() WHERE id = ? AND user_id = ?",
            [existing["id"], user_id],
        )
        return int(existing["id"])
    return db.execute(
        """
        INSERT INTO dbo.image_cases
            (user_id, user_key, sha256, original_name, stored_name, content_type, size_bytes,
             width, height, ocr_text, risk_score, risk_level, scam_type, summary,
             result_json, source)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            user_id,
            tenant.user_key(),
            sha256,
            original_name,
            stored_name,
            content_type,
            size_bytes,
            width,
            height,
            ocr_text,
            int(result.get("risk_score", 0)),
            result.get("risk_level", "low"),
            str(result.get("scam_type", ""))[:64],
            str(result.get("summary", ""))[:1000],
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            "upload",
        ],
        fetch_identity=True,
    )


def lookup_image(sha256: str) -> dict[str, Any] | None:
    row = db.query_one(
        """
        SELECT id, sha256, original_name, stored_name, ocr_text, risk_score,
               risk_level, scam_type, summary, result_json, hit_count
        FROM dbo.image_cases WHERE sha256 = ? AND user_id = ? AND is_active = 1 AND isdeleted = 0
        """,
        [sha256, tenant.user_id()],
    )
    if not row:
        return None
    result = {}
    try:
        value = json.loads(row.get("result_json") or "{}")
        if isinstance(value, dict):
            result = value
    except json.JSONDecodeError:
        pass
    row["result"] = result
    return row


def count_image_cases() -> int:
    row = db.query_one(
        "SELECT COUNT_BIG(*) AS total FROM dbo.image_cases WHERE user_id = ? AND is_active = 1 AND isdeleted = 0",
        [tenant.user_id()],
    )
    return int(row["total"]) if row else 0


def count_staging(user_key: str | None = None) -> int:
    row = db.query_one(
        "SELECT COUNT_BIG(*) AS total FROM dbo.staging_contents WHERE user_id = ? AND isdeleted = 0",
        [tenant.user_id()],
    )
    return int(row["total"]) if row else 0