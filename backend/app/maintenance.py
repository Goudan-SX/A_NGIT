"""预设数据库维护任务：清理过期/回收站数据，可由 root 管理员或 CLI 触发。

用法：
    python -m backend.app.maintenance
    POST /api/admin/maintenance   （仅 root）
"""
from __future__ import annotations

import json

from . import config, conversation_store, db, user_db


def run_all() -> dict[str, int]:
    """执行全部时效性维护，返回各表清理条数。"""
    result: dict[str, int] = {}
    result["conversations"] = conversation_store.cleanup()
    result["sessions"] = user_db.purge_expired_sessions()
    result["staging"] = int(db.execute(
        "DELETE FROM dbo.staging_contents WHERE expires_at IS NOT NULL AND expires_at < SYSDATETIME()"
    ) or 0)
    result["auto_cases"] = int(db.execute(
        "DELETE FROM dbo.text_cases WHERE source = 'auto' AND created_at < DATEADD(day, -90, SYSDATETIME())"
    ) or 0)
    result["recycle_bin"] = int(db.execute(
        "DELETE FROM dbo.analyses WHERE isdeleted = 1 AND deleted_at < DATEADD(day, -?, SYSDATETIME())",
        [int(config.SOFT_DELETE_RETENTION_DAYS)],
    ) or 0)
    return result


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False))
