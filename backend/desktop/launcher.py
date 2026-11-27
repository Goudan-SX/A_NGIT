"""Guardian-AI 桌面启动器：请求管理员权限，启动本地后端与托盘监测。

双击桌面快捷方式后由用户确认 UAC；确认后写入默认监测授权并启动。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "backend" / "data" / "launcher.log"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
PYTHON = Path(sys.executable)


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except OSError:
        pass


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def elevate() -> None:
    params = " ".join(['"' + str(Path(__file__)) + '"', "--elevated"])
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(PYTHONW), params, str(ROOT), 1)
    if result <= 32:
        log(f"UAC 提升失败：{result}")


def health() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False


def hidden_kwargs() -> dict:
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return {"startupinfo": info, "creationflags": 0x08000000}


def start_backend() -> bool:
    if health():
        return True
    log("启动后端")
    with (ROOT / "backend" / "data" / "backend.log").open("ab") as output:
        subprocess.Popen(
            [str(PYTHONW), "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT),
            stdout=output,
            stderr=subprocess.STDOUT,
            **hidden_kwargs(),
        )
    for _ in range(40):
        if health():
            return True
        time.sleep(0.5)
    return False


def candidate_titles() -> list[str]:
    try:
        from backend.desktop.guardian_tray import window_titles
        return [title for title in window_titles() if any(word.lower() in title.lower() for word in ("微信", "wechat", "qq", "tim", "企业微信", "wecom"))]
    except Exception:  # noqa: BLE001
        return []


def configure_tray() -> None:
    path = ROOT / "backend" / "data" / "tray_config.json"
    if path.exists():
        return
    titles = candidate_titles() or ["微信", "WeChat", "QQ", "TIM", "企业微信"]
    payload = {
        "allowed_titles": titles,
        "consent": True,
        "external_ai_consent": True,
        "paused": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log("写入默认监测窗口：" + "、".join(titles))


def tray_running() -> bool:
    pid_path = ROOT / "backend" / "data" / "tray.pid"
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


def start_tray() -> None:
    if tray_running():
        return
    log("启动托盘")
    subprocess.Popen(
        [str(PYTHONW), str(ROOT / "backend" / "desktop" / "guardian_tray.py")],
        cwd=str(ROOT),
        **hidden_kwargs(),
    )


def notify_result(ok: bool) -> None:
    try:
        from winotify import Notification
        Notification(
            app_id="Guardian-AI",
            title="Guardian-AI 已启动" if ok else "Guardian-AI 启动失败",
            msg="托盘监测已运行；可通过托盘暂停或退出。" if ok else "请查看 backend/data/launcher.log。",
            duration="short",
        ).show()
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    if "--elevated" not in sys.argv and not is_admin():
        elevate()
        return
    log("管理员权限已确认")
    configure_tray()
    ok = start_backend()
    if ok:
        start_tray()
    log("启动完成" if ok else "启动失败")
    notify_result(ok)


if __name__ == "__main__":
    main()
