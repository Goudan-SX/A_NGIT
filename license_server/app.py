# -*- coding: utf-8 -*-
"""Guardian-AI 授权/数据库接口（Flask）。

只暴露最小必要接口，不返回数据库连接串、服务器地址或 SQL 账号密码。
运行：python license_server/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request  # noqa: E402

from backend.app import config, user_db  # noqa: E402

app = Flask(__name__)
user_db.ensure_database()


@app.get("/health")
def health():
    try:
        user_db.query_one("SELECT 1 AS ok")
        return jsonify({"ok": True, "service": "license", "database": config.USER_DB_NAME})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:200]}), 503


@app.post("/api/license/verify")
def verify():
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key") or "").strip()
    if len(key) != 32:
        return jsonify({"ok": True, "valid": False, "message": "密钥格式不正确"})
    valid = user_db.verify_access_key(key)
    return jsonify({"ok": True, "valid": valid})


@app.get("/api/license/summary")
def summary():
    return jsonify({
        "ok": True,
        "max_users": config.MAX_USERS,
        "user_storage_gb": config.USER_STORAGE_GB,
        "total_storage_gb": 10,
        "reserved_gb": 3,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
