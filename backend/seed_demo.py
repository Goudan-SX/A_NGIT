"""初始化演示数据：python backend/seed_demo.py [--force]"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import analyzer, db, repository  # noqa: E402

SAMPLES = [
    (
        "text",
        "[11:42] 陌生好友：亲，动动手指日赚 300，刷单返利，先垫付后返还。\n"
        "[11:43] 陌生好友：你的账户被冻结了，把验证码发给我就能解冻。\n"
        "[11:44] 陌生好友：下载会议 App 并开启屏幕共享，我远程指导你操作。",
    ),
    (
        "text",
        "【客服】您的订单理赔已通过，请提供身份证 110101199003071234、"
        "手机号 13800138000、银行卡 6222021234567890123，并把短信验证码 123456 发给我。",
    ),
    (
        "text",
        "同学你好，明天下午 3 点在教学楼 302 开班会，请带好学生证，收到请回复。",
    ),
]


def main() -> None:
    force = "--force" in sys.argv
    db.ensure_database()
    row = db.query_one("SELECT COUNT_BIG(*) AS total FROM dbo.analyses")
    total = int(row["total"]) if row else 0
    if total and not force:
        print(f"已有 {total} 条记录，跳过。需要重置请加 --force")
        return
    if force:
        db.execute("DELETE FROM dbo.staging_contents")
        db.execute("DELETE FROM dbo.analyses")
        db.execute("DELETE FROM dbo.logs")
        print("已清空旧的分析记录、当前用户暂存与日志")

    created = 0
    for source, text in SAMPLES:
        result = analyzer.analyze_text(text)
        analysis_id = repository.save_analysis(
            source=source,
            input_text=text,
            note=None,
            result=result,
            duration_ms=1,
        )
        repository.add_log(
            level="warning" if result["risk_level"] in {"high", "critical"} else "info",
            event="analyze",
            message=f"演示数据：{result['risk_label']} {result['risk_score']} 分",
            meta={"analysis_id": analysis_id, "source": source, "demo": True},
            duration_ms=1,
        )
        created += 1
        print(f"已写入演示记录 #{analysis_id}：{result['risk_score']} 分 / {result['scam_type']}")
    repository.add_log(
        level="success",
        event="system",
        message="演示数据初始化完成",
        meta={"count": created},
    )
    print(f"完成，共写入 {created} 条演示记录。")


if __name__ == "__main__":
    main()
