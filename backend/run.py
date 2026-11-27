"""开发环境启动入口：python backend/run.py"""
from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import config  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(
        "backend.app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
        reload_dirs=[str(ROOT / "backend")],
    )
