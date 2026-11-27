"""Guardian-AI 桌面风险浮层。

首次高风险：白色卡片淡入、闪烁一次、5 秒后自动隐藏。
持续高风险：切换为红色卡片常驻，直到用户结束对话/窗口离开/退出程序。

Tk 必须在主线程运行，所以浮层是独立进程；托盘通过状态文件发指令。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE = _ROOT / "backend" / "data" / "overlay_state.json"
_LOG = _ROOT / "backend" / "data" / "overlay.log"
_LOCK = threading.Lock()
_PROCESS: subprocess.Popen | None = None
_STATE_DATA: dict = {"foreground": False}
_FOREGROUND = False


def _log(message: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except OSError:
        pass


def _write_state() -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_STATE_DATA, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _STATE)
    except OSError:
        pass


def _start() -> None:
    global _PROCESS
    with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            return
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = str(pythonw if pythonw.exists() else sys.executable)
        _PROCESS = subprocess.Popen(
            [executable, str(Path(__file__).resolve()), "--serve"],
            cwd=str(_ROOT),
            creationflags=0x08000000,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def alert(score: int, summary: str, window_title: str = "") -> None:
    _STATE_DATA.update({
        "foreground": _FOREGROUND,
        "score": int(score),
        "summary": str(summary or ""),
        "window": str(window_title or ""),
        "nonce": uuid.uuid4().hex,
        "stop": False,
        "ts": time.time(),
    })
    _start()
    _write_state()


def set_foreground(active: bool) -> None:
    global _FOREGROUND
    _FOREGROUND = bool(active)
    _STATE_DATA["foreground"] = _FOREGROUND
    if _PROCESS is not None and _PROCESS.poll() is None:
        _write_state()


def shutdown() -> None:
    global _PROCESS
    _STATE_DATA["stop"] = True
    _write_state()
    if _PROCESS is not None:
        try:
            _PROCESS.join(timeout=1.5)
        except Exception:  # noqa: BLE001
            pass
        if _PROCESS.poll() is None:
            _PROCESS.terminate()
        _PROCESS = None


def _read_state() -> dict:
    try:
        value = json.loads(_STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _serve() -> None:
    foreground_active = False
    foreground_at = time.monotonic()
    last_alert_at = 0.0
    persistent = False
    hide_job = None
    flash_job = None
    last_nonce = ""

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#ffffff")
    width, height = 430, 150
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max(12, screen_w - width - 24)
    y = max(12, screen_h - height - 56)
    root.geometry(f"{width}x{height}+{x}+{y}")

    wrap = tk.Frame(root, bg="#ffffff", highlightthickness=2, highlightbackground="#dc2626")
    wrap.pack(fill="both", expand=True)
    head = tk.Label(wrap, text="Guardian-AI 风险提醒", bg="#ffffff", fg="#b91c1c",
                    font=("Microsoft YaHei", 10, "bold"), anchor="w")
    head.pack(fill="x", padx=14, pady=(9, 0))
    title = tk.Label(wrap, text="", bg="#ffffff", fg="#111111",
                     font=("Microsoft YaHei", 15, "bold"), anchor="w")
    title.pack(fill="x", padx=14, pady=(2, 0))
    body = tk.Label(wrap, text="", bg="#ffffff", fg="#4b5563",
                    font=("Microsoft YaHei", 10), justify="left", anchor="w", wraplength=395)
    body.pack(fill="both", expand=True, padx=14, pady=(2, 8))

    def no_activate() -> None:
        try:
            hwnd = root.winfo_id()
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception:  # noqa: BLE001
            pass

    def clear_jobs() -> None:
        nonlocal hide_job, flash_job
        for job in (hide_job, flash_job):
            if job:
                try:
                    root.after_cancel(job)
                except tk.TclError:
                    pass
        hide_job = None
        flash_job = None

    def hide() -> None:
        nonlocal persistent
        clear_jobs()
        root.withdraw()
        persistent = False

    def set_colors(red: bool) -> None:
        bg = "#dc2626" if red else "#ffffff"
        fg = "#ffffff" if red else "#111111"
        sub = "#fee2e2" if red else "#4b5563"
        root.configure(bg=bg)
        wrap.configure(bg=bg, highlightbackground="#ffffff" if red else "#dc2626")
        for widget in (head, title, body):
            widget.configure(bg=bg)
        head.configure(fg=sub)
        title.configure(fg=fg)
        body.configure(fg=sub)

    def fade_in() -> None:
        alpha = 0.0
        def step() -> None:
            nonlocal alpha
            alpha = min(0.94, alpha + 0.12)
            try:
                root.attributes("-alpha", alpha)
            except tk.TclError:
                return
            if alpha < 0.94:
                root.after(24, step)
        step()

    def flash() -> None:
        nonlocal flash_job
        def tick(count: int = 0) -> None:
            nonlocal flash_job
            if count >= 4 or persistent:
                set_colors(False)
                return
            set_colors(count % 2 == 1)
            flash_job = root.after(140, lambda: tick(count + 1))
        tick()

    def schedule_hide() -> None:
        nonlocal hide_job
        if persistent:
            return
        hide_job = root.after(5000, hide)

    def on_alert(score: int, summary: str, window_title: str) -> None:
        nonlocal last_alert_at, persistent, hide_job
        now = time.monotonic()
        repeated = (now - last_alert_at) < 60 and last_alert_at > 0
        last_alert_at = now
        # 分数 >=90 直接红色常驻；70-89 首次白色闪烁、5 秒自动关闭，
        # 短时间（60 秒内）重复命中也升级为红色常驻。
        persistent = repeated or score >= 90
        clear_jobs()
        set_colors(persistent)
        head.configure(text="Guardian-AI · 持续高风险" if persistent else "Guardian-AI 风险提醒")
        title.configure(text=f"疑似诈骗风险 {score}%")
        detail = summary[:220] if summary else "检测到高度可疑的诈骗行为，请立即停止转账、共享屏幕或发送验证码。"
        body.configure(text=detail + (f"\n来源：{window_title[:60]}" if window_title else ""))
        root.deiconify()
        root.attributes("-alpha", 0.0)
        root.lift()
        root.attributes("-topmost", True)
        no_activate()
        fade_in()
        _log(f"show score={score} persistent={repeated} geom={root.winfo_geometry()}")
        if repeated:
            hide_job = None
        else:
            schedule_hide()
            flash()

    def poll_state() -> None:
        nonlocal foreground_active, foreground_at, persistent, last_nonce
        state = _read_state()
        if state.get("stop"):
            clear_jobs()
            root.destroy()
            return
        if "foreground" in state:
            foreground_active = bool(state["foreground"])
            if foreground_active:
                foreground_at = time.monotonic()
        nonce = str(state.get("nonce") or "")
        if nonce and nonce != last_nonce:
            last_nonce = nonce
            on_alert(int(state.get("score", 0)), str(state.get("summary", "")), str(state.get("window", "")))
        if persistent and not foreground_active and time.monotonic() - foreground_at > 12:
            hide()
        root.after(250, poll_state)

    root.after(250, poll_state)
    root.mainloop()


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
