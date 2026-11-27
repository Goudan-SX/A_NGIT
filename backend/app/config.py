"""反诈卫士后端配置。

所有配置均可通过环境变量或项目根目录 .env 覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
ROOT_DIR = BASE_DIR.parent                                 # 仓库根目录
FRONTEND_DIR = ROOT_DIR / "HTML+CSS"
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
THUMB_DIR = DATA_DIR / "thumbnails"


def load_dotenv() -> None:
    """极简 .env 读取，避免为了一个配置引入额外依赖。"""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

APP_NAME = "反诈卫士 API"
APP_VERSION = "1.0.0"
HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))

# --------------------------------------------------------------------------
# SQL Server（默认使用本机 LocalDB，可通过 .env 切换到正式 SQL Server）
# --------------------------------------------------------------------------
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("DB_SERVER", r"(localdb)\MSSQLLocalDB")
DB_NAME = os.getenv("DB_NAME", "AntiFraudGuard")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_TRUSTED = os.getenv("DB_TRUSTED", "yes").lower() in {"1", "yes", "true", "on"}
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "no")
DB_TIMEOUT = int(os.getenv("DB_TIMEOUT", "10"))

# --------------------------------------------------------------------------
# Qwen / 通义千问（优先使用的多模态能力）
# 未配置 Key 时系统自动降级为本地规则引擎，不影响基础功能演示。
# --------------------------------------------------------------------------
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "").strip()
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
QWEN_TEXT_MODEL = os.getenv("QWEN_TEXT_MODEL", "qwen-plus")
QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen-vl-max")
QWEN_AUDIO_MODEL = os.getenv("QWEN_AUDIO_MODEL", "qwen3-asr-flash")
QWEN_TIMEOUT = int(os.getenv("QWEN_TIMEOUT", "60"))
QWEN_ENABLED = bool(QWEN_API_KEY)

# --------------------------------------------------------------------------
# 上传限制
# --------------------------------------------------------------------------
MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "10"))
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "25"))
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".webm", ".flac", ".amr"}

for folder in (DATA_DIR, UPLOAD_DIR, THUMB_DIR):
    folder.mkdir(parents=True, exist_ok=True)
