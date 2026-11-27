# -*- coding: utf-8 -*-
"""Build a clean Guardian-AI release ZIP (no secrets, runtime data or local DB)."""
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
    if path.name == ".env":
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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    name = f"Guardian-AI_v{version()}_{stamp}.zip"
    target = OUT_DIR / name
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and include(p))
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            zf.write(path, f"Guardian-AI/{rel}")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (OUT_DIR / (name + ".sha256.txt")).write_text(f"{digest}  {name}\n", encoding="utf-8")
    print(f"已生成：{target}")
    print(f"文件数：{len(files)}  大小：{target.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"SHA256：{digest}")


if __name__ == "__main__":
    main()
