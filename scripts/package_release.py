# -*- coding: utf-8 -*-
"""Build Guardian-AI server and client release ZIPs (no secrets/runtime data)."""
from __future__ import annotations

import hashlib
import re
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dist"
SKIP_DIRS = {".git", ".dsh-meow", ".venv", "node_modules", "__pycache__", "dist", ".pytest_cache"}
SKIP_PARTS = {("docs", "previews"), ("docs", "测试用")}
SKIP_SUFFIXES = {".pyc", ".log", ".pid", ".bak"}
DATA_ALLOW = {
    "backend/data/case_library.csv",
    "backend/data/guardian_cases.json",
    "backend/data/guardian_keywords.json",
    "backend/data/uploads/.gitkeep",
    "backend/data/thumbnails/.gitkeep",
}
CLIENT_FILES = [
    "Client-Setup.bat",
    "scripts/client_setup.ps1",
    "backend/desktop/guardian.ico",
    "README_客户端安装说明.md",
]
SERVER_EXCLUDE = {"Client-Setup.bat", "scripts/client_setup.ps1", "README_客户端安装说明.md"}


def version() -> str:
    text = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "unknown"


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if parts and parts[0] == "database":
        return False
    if any(part in SKIP_DIRS for part in parts):
        return False
    if any(parts[:2] == item for item in SKIP_PARTS):
        return False
    if path.name in {".env", "access_key.txt"}:
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    if path.name.startswith("preview-"):
        return False
    if parts[:2] == ("backend", "data"):
        posix = rel.as_posix()
        if posix in DATA_ALLOW:
            return True
        if len(parts) >= 3 and parts[2] == "guardian_source":
            return True
        return False
    return True


def build(files: list[Path], zip_name: str, prefix: str) -> Path:
    target = OUT_DIR / zip_name
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            zf.write(path, f"{prefix}/{rel}")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (OUT_DIR / (zip_name + ".sha256.txt")).write_text(f"{digest}  {zip_name}\n", encoding="utf-8")
    print(f"已生成：{target}")
    print(f"文件数：{len(files)}  大小：{target.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"SHA256：{digest}")
    return target


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    ver = version()

    server_files = sorted(
        p for p in ROOT.rglob("*")
        if p.is_file() and include(p)
        and p.relative_to(ROOT).as_posix() not in SERVER_EXCLUDE
    )
    client_files = [ROOT / rel for rel in CLIENT_FILES if (ROOT / rel).is_file()]

    build(server_files, f"Guardian-AI_Server_v{ver}_{stamp}.zip", "Guardian-AI-Server")
    print("")
    build(client_files, f"Guardian-AI_Client_v{ver}_{stamp}.zip", "Guardian-AI-Client")


if __name__ == "__main__":
    main()
