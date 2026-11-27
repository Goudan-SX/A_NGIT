"""Guardian-AI 本地托盘后台服务。

仅用户主动启动后运行；只有被勾选的前台社交窗口才采集可见文本，
默认不写原始文本、不读输入框/密码框/Cookie；风险 >=70 才发系统通知。
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
from difflib import SequenceMatcher
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from io import BytesIO
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

from backend.app import analyzer, config, conversation_store, ocr, security  # noqa: E402
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
_last_ai_alert_id = ""
GENERIC_CONTACTS = {"微信", "WeChat", "QQ", "TIM", "搜索", "发送", "未知用户"}
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


def collect_chat_texts(control, pane_left: int, top_y: int, deadline: float,
                       depth: int = 0, rows: list[tuple[int, int, str]] | None = None) -> list[tuple[int, int, str]]:
    rows = rows if rows is not None else []
    if time.monotonic() > deadline or depth > 5 or len(rows) >= 120:
        return rows
    try:
        ctype = control.ControlTypeName
        if ctype in {"TextControl", "DocumentControl"}:
            name = (control.Name or "").strip()
            rect = visible_rect(control)
            if name and rect and len(name) <= 800:
                left, top, right, bottom = rect
                if left >= pane_left and top >= top_y:
                    rows.append((top, left, name))
        for child in control.GetChildren():
            collect_chat_texts(child, pane_left, top_y, deadline, depth + 1, rows)
    except Exception:  # noqa: BLE001
        pass
    return rows


_LAYOUT_CACHE: dict[tuple, dict] = {}


def detect_chat_layout(rect: tuple[int, int, int, int], window_title: str) -> dict | None:
    """让视觉模型识别聊天范围；按窗口尺寸缓存 5 分钟。"""
    left, top, right, bottom = rect
    key = (window_title, right - left, bottom - top, int(time.time() // 300))
    cached = _LAYOUT_CACHE.get(key)
    if cached:
        return cached
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab(bbox=rect)
        if image.width > 1280:
            image = image.resize((1280, max(1, int(image.height * 1280 / image.width))))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        payload = json.dumps({
            "image_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "mime": "image/png",
        }).encode("utf-8")
        request = Request(
            API_BASE + "/api/monitor/layout",
            data=payload,
            headers={"Content-Type": "application/json", "X-Guardian-Token": security.get_local_token()},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        layout = data.get("layout") or {}
        if float(layout.get("confidence") or 0) < 0.35:
            return None
        chat = layout.get("chat") or {}
        contact = layout.get("contact") or {}
        if not all(isinstance(chat.get(k), (int, float)) for k in ("x", "y", "w", "h")):
            return None
        if contact:
            try:
                cw, ch = image.size
                cx = int(float(contact.get("x", 0)) * cw)
                cy = int(float(contact.get("y", 0)) * ch)
                cw_box = int(float(contact.get("w", 0)) * cw)
                ch_box = int(float(contact.get("h", 0)) * ch)
                # 模型框可能只框到状态点，向四周扩一圈再识别文字。
                box = (max(0, cx - 25), max(0, cy - 15),
                       min(cw, cx + max(200, cw_box + 160)), min(ch, cy + max(70, ch_box + 45)))
                if box[2] > box[0] and box[3] > box[1]:
                    crop = image.crop(box)
                    buf = BytesIO()
                    crop.save(buf, "PNG")
                    contact_payload = json.dumps({
                        "image_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                        "mime": "image/png",
                    }).encode("utf-8")
                    contact_req = Request(
                        API_BASE + "/api/monitor/contact",
                        data=contact_payload,
                        headers={"Content-Type": "application/json", "X-Guardian-Token": security.get_local_token()},
                        method="POST",
                    )
                    with urlopen(contact_req, timeout=30) as contact_resp:
                        layout["contact_text"] = str(json.loads(contact_resp.read().decode("utf-8")).get("text") or "").strip()
            except Exception:  # noqa: BLE001
                pass
        _LAYOUT_CACHE.clear()
        _LAYOUT_CACHE[key] = layout
        return layout
    except Exception:  # noqa: BLE001
        return None


def _box_screen(box: dict, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    try:
        x = left + int(float(box["x"]) * width)
        y = top + int(float(box["y"]) * height)
        w = int(float(box["w"]) * width)
        h = int(float(box["h"]) * height)
        if w < 60 or h < 20:
            return None
        return (max(left, x), max(top, y), min(right, x + w), min(bottom, y + h))
    except Exception:  # noqa: BLE001
        return None


def _ocr_region(crop: tuple[int, int, int, int], mask_overlay: bool = False) -> str:
    from PIL import ImageGrab, ImageDraw
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        path = handle.name
    try:
        image = ImageGrab.grab(bbox=crop)
        if mask_overlay:
            # 去掉右下角告警浮层，避免把浮层文字当成聊天内容。
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            box = (screen_w - 454 - crop[0], screen_h - 206 - crop[1],
                   screen_w - 24 - crop[0], screen_h - 56 - crop[1])
            ImageDraw.Draw(image).rectangle(box, fill=(255, 255, 255))
        image.save(path, "PNG")
        return ocr.extract_text(path, timeout=20)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _ocr_region_lines(crop: tuple[int, int, int, int], mask_overlay: bool = False) -> list[dict]:
    from PIL import ImageGrab, ImageDraw
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        path = handle.name
    try:
        image = ImageGrab.grab(bbox=crop)
        if mask_overlay:
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            box = (screen_w - 454 - crop[0], screen_h - 206 - crop[1],
                   screen_w - 24 - crop[0], screen_h - 56 - crop[1])
            ImageDraw.Draw(image).rectangle(box, fill=(255, 255, 255))
        image.save(path, "PNG")
        return ocr.extract_lines(path, timeout=30)
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def ocr_chat_snapshot(rect: tuple[int, int, int, int], window_title: str) -> tuple[str, list[str]] | None:
    """统一视觉采集：AI 定位范围，只取对方消息，过滤自己的输出。"""
    global _last_ocr_at
    now = time.time()
    if now - _last_ocr_at < 10:
        return None
    _last_ocr_at = now
    left, top, right, bottom = rect
    layout = detect_chat_layout(rect, window_title)
    header_box = _box_screen((layout or {}).get("contact") or {}, rect)
    chat_box = _box_screen((layout or {}).get("chat") or {}, rect)
    if not header_box:
        header_box = (left + int((right - left) * 0.25), top + 30, right, top + 125)
    if not chat_box:
        chat_box = (left + int((right - left) * 0.25), top + 115, right, bottom)

    contact = str((layout or {}).get("contact_text") or "").strip()[:60]
    # 先排除模型把窗口标题/当前用户昵称当联系人的情况，再回退到头部 OCR。
    def is_self_title(value: str) -> bool:
        if not value or not window_title:
            return False
        cnorm = value.strip().replace("舊", "旧")
        wnorm = window_title.strip().replace("舊", "旧")
        return cnorm == wnorm or (len(cnorm) >= 2 and (cnorm in wnorm or wnorm in cnorm)) or SequenceMatcher(None, cnorm, wnorm).ratio() >= 0.75
    if contact and is_self_title(contact):
        contact = ""
    if not contact or contact in GENERIC_CONTACTS:
        header_text = _ocr_region(header_box)
        for line in (header_text or "").splitlines():
            cleaned = line.strip(" ·|｜")
            if len(cleaned) <= 60 and cleaned not in GENERIC_CONTACTS and not re.fullmatch(r"\d{1,2}:\d{2}", cleaned) and not is_self_title(cleaned):
                contact = cleaned[:60]
                break
    if not contact or contact in GENERIC_CONTACTS or is_self_title(contact):
        return None

    rows = _ocr_region_lines(chat_box, mask_overlay=True)
    if not rows:
        return None
    width = max(1, chat_box[2] - chat_box[0])
    messages = []
    for row in rows:
        value = str(row.get("text") or "").strip()
        value = re.sub(r"^\d{1,2}:\d{2}\s*", "", value).strip()
        if not value or value == contact or _is_chat_noise(value):
            continue
        # 对方消息在左侧；右侧头像/气泡属于当前用户，不参与检测。
        center = int(row.get("x", 0)) + int(row.get("w", 0)) / 2
        if center > width * 0.62:
            continue
        messages.append(value[:500])
    if not messages:
        return None
    return contact, messages[-20:]


def read_chat_snapshot(window_title: str) -> tuple[str, list[str]] | None:
    """只读取当前聊天主区域：过滤左侧会话栏/搜索栏，保留不同消息文本。"""
    try:
        top = auto.GetForegroundControl().GetTopLevelControl()
        rect = visible_rect(top)
        if not rect:
            return None
        left, top_y, right, bottom = rect
        # 统一视觉采集：微信、QQ、TIM 及后续需要适配的聊天软件
        # 都先由 AI 识别聊天范围，再 OCR 联系人区和消息区；UIA 只作兜底。
        visual = ocr_chat_snapshot(rect, window_title)
        if visual:
            return visual
        pane_left = left + max(240, int((right - left) * 0.25))
        texts = collect_chat_texts(top, pane_left, top_y + 35, time.monotonic() + 0.5)
        if not texts:
            return ocr_chat_snapshot(rect, window_title)
        texts.sort(key=lambda item: (item[0], item[1]))
        header = []
        messages = []
        for y, x, value in texts:
            if y <= top_y + 115:
                if value not in {"搜索", "发送", "微信"} and not re.fullmatch(r"\d{1,2}:\d{2}", value):
                    header.append(value)
            elif not re.fullmatch(r"\d{1,2}:\d{2}", value):
                messages.append(value)
        contact = (header[0] if header else (window_title or "未知用户")).strip()[:60]
        if contact in GENERIC_CONTACTS:
            return None
        # 从最新消息往前截取，避免长文本把输入/请求拖慢。
        cleaned = []
        total = 0
        for value in reversed(messages):
            value = value.strip()
            if _is_chat_noise(value):
                continue
            value = value[:500]
            if total + len(value) > 3000:
                break
            cleaned.append(value)
            total += len(value)
        cleaned.reverse()
        if not cleaned:
            return ocr_chat_snapshot(rect, window_title)
        return contact, cleaned
    except Exception:  # noqa: BLE001
        return None


def _is_chat_noise(value: str) -> bool:
    noisy = ("按住", "语音输入", "发送", "搜索", "长按鼠标", "表情", "聊天信息", "折叠置顶")
    return len(value.strip()) < 2 or any(word in value for word in noisy)


def format_chat(contact: str, messages: list[str]) -> str:
    stamp = time.strftime("%H:%M")
    return "\n".join(f"{stamp} ： {contact}：{message}" for message in messages)


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
    try:
        if _icon:
            _icon.notify(f"风险 {result.get('risk_score', 0)}%：{(result.get('summary') or '')[:80]}", "Guardian-AI")
    except Exception:  # noqa: BLE001
        pass


def check_ai_alert() -> None:
    """后台 AI 初审完成后，托盘主动拉取并优先弹本机告警。"""
    global _last_ai_alert_id
    try:
        request = Request(
            API_BASE + "/api/monitor/latest",
            headers={"Accept": "application/json", "X-Guardian-Token": security.get_local_token()},
            method="GET",
        )
        with urlopen(request, timeout=3) as response:
            item = json.loads(response.read().decode("utf-8")).get("item") or {}
        if item.get("source") != "tray-ai":
            return
        result = item.get("result") or {}
        score = int(result.get("risk_score", 0))
        if score < 70 or item.get("id") == _last_ai_alert_id:
            return
        _last_ai_alert_id = str(item.get("id") or "")
        window = str(item.get("window") or "当前对话")
        alert_overlay.alert(score, str(result.get("summary", "")), window)
        record_alert(window, result)
        notify(window, result)
    except Exception:  # noqa: BLE001
        pass


def tick() -> None:
    global _last_hash, _last_alert_at, _last_alert_key
    if _paused or _stop.is_set():
        return
    check_ai_alert()
    found = foreground_window()
    active = bool(found and allowed(found[0]))
    alert_overlay.set_foreground(active)
    if not found or not active:
        return
    title = found[0]
    snapshot = read_chat_snapshot(title)
    if not snapshot:
        return
    contact, messages = snapshot
    text = format_chat(contact, messages)
    digest = hashlib.sha256((contact + "|" + text).encode("utf-8", errors="ignore")).hexdigest()
    if digest == _last_hash:
        return
    _last_hash = digest
    data = analyze(text, contact)
    if not data or not data.get("analysis"):
        return
    result = data["analysis"]
    conversation_store.save(
        contact_id=contact,
        contact_name=contact,
        window_title=title,
        text=analyzer.mask_text(text, result),
        result=result,
    )
    score = int(result.get("risk_score", 0))
    if score >= 70:
        alert_overlay.alert(score, str(result.get("summary", "")), contact)
        key = digest[:16]
        if key != _last_alert_key or time.time() - _last_alert_at > ALERT_COOLDOWN:
            _last_alert_key = key
            _last_alert_at = time.time()
            record_alert(contact, result)
            notify(contact, result)
    # 本机告警已经触发后，再把数据同步给 Web；Web 允许延迟，但不能反超本机。
    publish_result(text, result, title)
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