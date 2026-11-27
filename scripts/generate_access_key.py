# -*- coding: utf-8 -*-
"""生成/轮换统一访问密钥，明文只写入项目根目录 access_key.txt。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import user_db  # noqa: E402


def main() -> int:
    user_db.ensure_database()
    key = user_db.generate_access_key()
    path = ROOT / "access_key.txt"
    path.write_text(key + "\n", encoding="utf-8")
    print(f"已生成新的统一访问密钥：{path}")
    print("旧密钥已立即失效；请将新密钥发给普通用户。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
