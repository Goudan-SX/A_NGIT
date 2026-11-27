"""Guardian-AI 本地托盘后台服务。

仅用户主动启动后运行；只有被勾选的前台社交窗口才采集可见文本，
默认不写原始文本、不读输入框/密码框/Cookie；风险 >=70 才发系统通知。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import uiautomation as auto
from uiautomation import UIAutomationInitializerInThread
from PIL import Image, ImageDraw, ImageFont
from pystray import Icon, Menu, MenuItem

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import analyzer, config, ocr, security  # noqa: E402
from backend.desktop import alert_overlay, single_instance  # noqa: E402

CONFIG_PATH = config.DATA_DIR / "tray_config.json"
QUEUE_PATH = config.DATA_DIR / "tray_alerts.db"
PID_PATH = config.DATA_DIR / "tray.pid"
BACKEND_PID = config.DATA_DIR / "backend.pid"
API_BASE = "http://127.0.0.1:8000"
POLL_SECONDS = 1.5
ALERT_COOLDOWN = 600
_last_hash = ""
_last_alert_at = 0.0
_last_alert_key = ""
_last_ocr_at = 0.0
_stop = threading.Event()
_paused = False
_allowed_titles: list[str] = []
_icon: Icon | None = None
_TRAY_MUTEX = None


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def window_titles() -> list[str]:
    titles = []
    try:
        for window in auto.GetRootControl().GetChildren():
            try:
                name = (window.Name or "").strip()
                if name and name not in titles and window.ControlTypeName == "WindowControl":
                    titles.append(name[:100])
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return titles


def choose_windows(first_run: bool = False) -> bool:
    """首次启动授权说明 + 勾选要监测的窗口。"""
    root = tk.Tk()
    root.title("Guardian-AI 本地监测授权")
    root.geometry("560x520")
    root.attributes("-topmost", True)
    tk.Label(root, text="只在被勾选窗口处于前台时读取屏幕可见文本", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
    tk.Label(root, text="不读取输入框、密码框、Cookie 或历史消息；不写入原始文本；风险 >=70 才弹系统通知。", wraplength=520, justify="left").pack(anchor="w", padx=16)
    listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, height=14)
    listbox.pack(fill="both", expand=True, padx=16, pady=10)
    titles = window_titles()
    for title in titles:
        listbox.insert(tk.END, title)
    if _allowed_titles:
        for index, title in enumerate(titles):
            if title in _allowed_titles:
                listbox.selection_set(index)
    consent = tk.BooleanVar(value=False if first_run else True)
    tk.Checkbutton(root, text="我已知晓并同意仅监测所选窗口的可见文本", variable=consent).pack(anchor="w", padx=16)
    external = tk.BooleanVar(value=bool(load_config().get("external_ai_consent", True)))
    tk.Checkbutton(root, text="允许脱敏后调用外部大模型；关闭则只用本地规则/基础库", variable=external).pack(anchor="w", padx=16)
    result = {"ok": False}
    def submit() -> None:
        if not consent.get():
            messagebox.showwarning("未授权", "需要勾选授权说明后才能启动。")
            return
        selected = [titles[i] for i in listbox.curselection()]
        if not selected:
            messagebox.showwarning("未选择窗口", "至少选择一个要监测的窗口。")
            return
        global _allowed_titles
        _allowed_titles = selected
        save_config({"allowed_titles": selected, "consent": True, "paused": False, "external_ai_consent": bool(external.get())})
        result["ok"] = True
        root.destroy()
    def cancel() -> None:
        root.destroy()
    actions = tk.Frame(root)
    actions.pack(fill="x", padx=16, pady=10)
    tk.Button(actions, text="保存并开始监测", command=submit, bg="#2563eb", fg="white", padx=14, pady=6).pack(side="right")
    tk.Button(actions, text="取消", command=cancel, padx=14, pady=6).pack(side="right", padx=8)
    root.mainloop()
    return bool(result["ok"])


def icon_image() -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((5, 5, size - 5, size - 5), outline=(17, 17, 17, 255), width=5)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 36)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), "G", font=font)
    draw.text(((size - (box[2] - box[0])) / 2, (size - (box[3] - box[1])) / 2 - 2), "G", fill=(17, 17, 17, 255), font=font)
    return image


def visible_rect(control) -> tuple[int, int, int, int] | None:
    try:
        rect = control.BoundingRectangle
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:  # noqa: BLE001
        return None


def collect_controls(control, depth: int = 0, rows: list[str] | None = None,
                     deadline: float | None = None) -> list[str]:
    rows = rows if rows is not None else []
    if deadline is None:
        deadline = time.monotonic() + 0.35
    if time.monotonic() > deadline or depth > 4 or len(rows) >= 60:
        return rows
    try:
        control_type = control.ControlTypeName
        if control_type in {"TextControl", "DocumentControl"}:
            name = (control.Name or "").strip()
            if name and len(name) <= 500 and visible_rect(control):
                rows.append(name)
        elif control_type == "EditControl":
            # 明确不读取输入框/密码框。
            pass
        for child in control.GetChildren():
            collect_controls(child, depth + 1, rows, deadline)
    except Exception:  # noqa: BLE001
        pass
    return rows


def foreground_window() -> tuple[str, str] | None:
    try:
        control = auto.GetForegroundControl()
        if not control:
            return None
        top = control.GetTopLevelControl()
        title = (top.Name or "").strip()
        if not title:
            return None
        return title, hashlib.sha1(str(top.NativeWindowHandle).encode()).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def allowed(title: str) -> bool:
    return any(item and (item == title or item in title or title in item) for item in _allowed_titles)


def read_visible_text(window_title: str) -> str:
    try:
        control = auto.GetForegroundControl().GetTopLevelControl()
        rows = collect_controls(control, deadline=time.monotonic() + 0.4)
        text = "\n".join(rows).strip()
        if len(text) >= 4:
            return text[-4000:]
        # 控件树读不到文字时才截图 OCR，限制频率且不落盘。
        global _last_ocr_at
        if time.time() - _last_ocr_at < 10:
            return ""
        _last_ocr_at = time.time()
        rect = visible_rect(control)
        if not rect:
            return ""
        from PIL import ImageGrab
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = handle.name
        try:
            ImageGrab.grab(bbox=rect).save(path, "PNG")
            return (ocr.extract_text(path) or "")[-4000:]
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        return ""


def analyze(text: str, window_title: str) -> dict | None:
    """托盘专用快速通道：只跑本地规则，不等 DeepSeek。"""
    token = security.get_local_token()
    payload = json.dumps({
        "text": text,
        "window": window_title[:120],
        "client_id": "tray-service",
    }).encode("utf-8")
    request = Request(
        API_BASE + "/api/monitor/analyze",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Guardian-Token": token,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def publish_result(text: str, result: dict, window_title: str) -> None:
    token = security.get_local_token()
    payload = json.dumps({
        "text": text,
        "result": result,
        "source": "tray",
        "window": window_title[:120],
    }).encode("utf-8")
    request = Request(
        API_BASE + "/api/monitor/publish",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Guardian-Token": token,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10):
            pass
    except Exception:  # noqa: BLE001
        pass


def record_alert(window_title: str, result: dict) -> None:
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(QUEUE_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, window_title TEXT, risk_score INTEGER, risk_level TEXT, summary TEXT)"
            )
            conn.execute(
                "INSERT INTO alerts (created_at, window_title, risk_score, risk_level, summary) VALUES (datetime('now','localtime'), ?, ?, ?, ?)",
                (window_title[:100], int(result.get("risk_score", 0)), str(result.get("risk_level", "")), str(result.get("summary", ""))[:500]),
            )
    except sqlite3.Error:
        pass


def notify(window_title: str, result: dict) -> None:
    try:
        from winotify import Notification
        toast = Notification(
            app_id="Guardian-AI",
            title=f"Guardian-AI 风险提醒 {result.get('risk_score', 0)}%",
            msg=(result.get("summary") or "检测到可疑聊天内容，请打开面板查看。")[:180],
            duration="short",
            launch=API_BASE + "/",
        )
        toast.show()
    except Exception:  # noqa: BLE001
        pass


def tick() -> None:
    global _last_hash, _last_alert_at, _last_alert_key
    if _paused or _stop.is_set():
        return
    found = foreground_window()
    active = bool(found and allowed(found[0]))
    alert_overlay.set_foreground(active)
    if not found or not active:
        return
    title = found[0]
    text = read_visible_text(title)
    if len(text) < 4:
        return
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    if digest == _last_hash:
        return
    _last_hash = digest
    data = analyze(text, title)
    if not data or not data.get("analysis"):
        return
    result = data["analysis"]
    score = int(result.get("risk_score", 0))
    if score >= 70:
        alert_overlay.alert(score, str(result.get("summary", "")), title)
        key = digest[:16]
        if key != _last_alert_key or time.time() - _last_alert_at > ALERT_COOLDOWN:
            _last_alert_key = key
            _last_alert_at = time.time()
            record_alert(title, result)
            notify(title, result)
    if _icon:
        _icon.title = f"Guardian-AI · 监测中 · 最近 {score}%"


def worker() -> None:
    try:
        with UIAutomationInitializerInThread():
            while not _stop.is_set():
                try:
                    tick()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(POLL_SECONDS)
    except Exception:  # noqa: BLE001
        pass


def toggle_pause(icon: Icon, item: MenuItem) -> None:
    global _paused
    _paused = not _paused
    cfg = load_config()
    cfg["paused"] = _paused
    save_config(cfg)
    icon.title = "Guardian-AI · 已暂停" if _paused else "Guardian-AI · 监测中"
    icon.update_menu()


def open_panel(icon: Icon, item: MenuItem) -> None:
    os.startfile(API_BASE + "/")


def choose_from_tray(icon: Icon, item: MenuItem) -> None:
    threading.Thread(target=choose_windows, kwargs={"first_run": False}, daemon=True).start()


def stop_backend() -> None:
    try:
        pid = 0
        try:
            pid = int(BACKEND_PID.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            try:
                request = Request(API_BASE + "/api/health", headers={"Accept": "application/json"})
                with urlopen(request, timeout=2) as response:
                    pid = int(json.loads(response.read().decode("utf-8")).get("pid") or 0)
            except Exception:  # noqa: BLE001
                pid = 0
        if pid and pid != os.getpid():
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
                timeout=5,
            )
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            BACKEND_PID.unlink()
        except OSError:
            pass


def quit_app(icon: Icon, item: MenuItem) -> None:
    _stop.set()
    alert_overlay.shutdown()
    stop_backend()
    icon.stop()


def main() -> None:
    global _allowed_titles, _paused, _icon, _TRAY_MUTEX
    _TRAY_MUTEX = single_instance.acquire()
    if _TRAY_MUTEX is None:
        return
    cfg = load_config()
    if not cfg.get("consent") or not cfg.get("allowed_titles"):
        if not choose_windows(first_run=True):
            return
        cfg = load_config()
    _allowed_titles = list(cfg.get("allowed_titles") or [])
    _paused = bool(cfg.get("paused"))
    _icon = Icon(
        "guardian-ai",
        icon_image(),
        "Guardian-AI · 已暂停" if _paused else "Guardian-AI · 监测中",
        Menu(
            MenuItem(lambda item: "Ⅱ 已暂停" if _paused else "● 监测中", toggle_pause),
            MenuItem("选择监测窗口", choose_from_tray),
            MenuItem("打开 Web 面板", open_panel),
            Menu.SEPARATOR,
            MenuItem("退出", quit_app),
        ),
    )
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    threading.Thread(target=worker, daemon=True).start()
    try:
        _icon.run()
    finally:
        try:
            PID_PATH.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()