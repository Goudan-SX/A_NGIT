# -*- coding: utf-8 -*-
"""Guardian-AI 首次安装初始化：建库建表、写入种子、生成 root 初始密码。"""
from __future__ import annotations

import re
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def ensure_env() -> Path:
    if not ENV_PATH.exists():
        if not ENV_EXAMPLE.exists():
            raise SystemExit("缺少 .env.example，无法生成配置文件")
        shutil.copyfile(ENV_EXAMPLE, ENV_PATH)
        print(f"已生成配置文件：{ENV_PATH}")
    return ENV_PATH


def read_env_value(key: str) -> str:
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def write_root_password(password: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    line = f"ROOT_PASSWORD={password}"
    if re.search(r"^ROOT_PASSWORD=.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^ROOT_PASSWORD=.*$", line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + "\n" + line + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    ensure_env()
    sys.path.insert(0, str(ROOT))
    from backend.app import config, db, user_db

    print("检查 SQL Server LocalDB 连接…")
    try:
        master = db.connect("master", autocommit=True)
        cur = master.cursor()
        main_exists = bool(cur.execute("SELECT DB_ID(?)", config.DB_NAME).fetchone()[0])
        user_exists = bool(cur.execute("SELECT DB_ID(?)", config.USER_DB_NAME).fetchone()[0])
        master.close()
    except Exception as exc:  # noqa: BLE001
        print(f"无法连接 SQL Server：{exc}")
        print("请先安装 SQL Server LocalDB 2019+ 和 ODBC Driver 17 for SQL Server。")
        return 1

    fresh = not main_exists and not user_exists
    provided_password = read_env_value("ROOT_PASSWORD")
    root_password = provided_password or config.ROOT_PASSWORD
    if fresh:
        if not provided_password:
            root_password = secrets.token_urlsafe(12)
            write_root_password(root_password)
        config.ROOT_PASSWORD = root_password
        print("检测到全新安装，管理员凭据已初始化。")
    else:
        print("检测到已有数据库，保留现有管理员凭据。")

    print("创建/升级数据库结构并写入种子数据…")
    db.ensure_database()
    user_db.ensure_database()

    from backend.app import case_matcher, guardian, transaction_risk
    created = case_matcher.seed_cases()
    guardian.ensure_data()
    transaction_risk.ensure_rules()

    access_key_path = ROOT / "access_key.txt"
    if not user_db.has_active_access_key():
        access_key = user_db.generate_access_key()
        access_key_path.write_text(access_key + "\n", encoding="utf-8")
        print(f"已生成统一访问密钥：{access_key_path}")
    elif access_key_path.exists():
        print(f"访问密钥文件：{access_key_path}")
    else:
        print("数据库已有访问密钥；如本地文件丢失，可运行 scripts/generate_access_key.py 重新生成。")

    print("")
    print("=" * 56)
    print("Guardian-AI 初始化完成")
    print(f"项目目录：{ROOT}")
    print(f"数据库文件：{config.DB_DATA_DIR}")
    print(f"文本案例：{case_matcher.count_cases()} 条（新增种子 {created} 条）")
    print("账号登录/注册和访问密钥均在网页端使用。")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
