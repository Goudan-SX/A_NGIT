# -*- coding: utf-8 -*-
"""Guardian-AI 安装器：复制文件、收集配置、创建环境、初始化数据库、创建快捷方式。"""
from __future__ import annotations

import argparse
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
DATA_ALLOW = {
    "backend/data/case_library.csv",
    "backend/data/guardian_cases.json",
    "backend/data/guardian_keywords.json",
    "backend/data/uploads/.gitkeep",
    "backend/data/thumbnails/.gitkeep",
}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def default_target() -> Path:
    for drive in ("D:", "E:"):
        root = Path(drive + "\\")
        if root.exists():
            return root / "Guardian-AI"
    return Path.home() / "Guardian-AI"


def should_copy(path: Path) -> bool:
    rel = path.relative_to(SOURCE)
    parts = rel.parts
    if parts and parts[0] == "database":
        return False
    if any(part in {".git", ".venv", "dist", "__pycache__", ".dsh-meow"} for part in parts):
        return False
    if len(parts) >= 2 and parts[:2] in {("docs", "previews"), ("docs", "测试用")}:
        return False
    if path.name == ".env":
        return False
    if path.suffix.lower() in {".pyc", ".log", ".pid", ".bak"}:
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


def copy_project(target: Path, log) -> None:
    if target.resolve() == SOURCE.resolve():
        log("就地安装：跳过文件复制")
        return
    if SOURCE in target.parents or target in SOURCE.parents:
        raise RuntimeError("安装目录不能位于安装包内部或安装包的上级目录")
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in SOURCE.rglob("*"):
        if not path.is_file() or not should_copy(path):
            continue
        dest = target / path.relative_to(SOURCE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        count += 1
    log(f"已复制 {count} 个文件到 {target}")


def write_env(target: Path, port: str, root_password: str, log) -> None:
    env_path = target / ".env"
    if env_path.exists():
        template = env_path.read_text(encoding="utf-8")
        backup = env_path.with_name(f".env.bak.{secrets.token_hex(3)}")
        shutil.copy2(env_path, backup)
        log(f"已备份原 .env -> {backup.name}")
        match = re.search(r"^ROOT_PASSWORD=(.*)$", template, flags=re.MULTILINE)
        if match and match.group(1).strip():
            root_password = match.group(1).strip()
            log("检测到已有 .env，保留原 root 密码与 AI 配置")
    else:
        template = (target / ".env.example").read_text(encoding="utf-8")
    values = {
        "APP_HOST": "127.0.0.1",
        "APP_PORT": port,
        "ROOT_PASSWORD": root_password,
    }
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{re.escape(key)}=.*$", template, flags=re.MULTILINE):
            template = re.sub(rf"^{re.escape(key)}=.*$", lambda _m: line, template, flags=re.MULTILINE)
        else:
            template = template.rstrip() + "\n" + line + "\n"
    env_path.write_text(template, encoding="utf-8")
    log("已写入 .env 配置（AI Key 留空，登录后在网页 API 页配置）")


def run(cmd, cwd: Path, log) -> None:
    log("$ " + " ".join(str(item) for item in cmd))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [str(item) for item in cmd],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=NO_WINDOW,
    )
    assert process.stdout is not None
    for line in process.stdout:
        log(line.rstrip())
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"命令失败（退出码 {code}）：{' '.join(str(x) for x in cmd)}")


def install(target: Path, *, port: str, root_password: str,
            mirror: bool, shortcut: bool, start: bool, skip_deps: bool, log) -> None:
    target = target.resolve()
    log("=" * 52)
    log("Guardian-AI 安装开始")
    log(f"安装目录：{target}")
    copy_project(target, log)
    write_env(target, port, root_password, log)

    venv = target / ".venv"
    if skip_deps:
        python = Path(sys.executable)
        log("已跳过依赖安装（调试模式），使用当前 Python 初始化数据库")
    else:
        if not (venv / "Scripts" / "python.exe").exists():
            log("创建虚拟环境 .venv …")
            run([sys.executable, "-m", "venv", str(venv)], target, log)
        python = venv / "Scripts" / "python.exe"
        log("升级 pip …")
        run([python, "-m", "pip", "install", "--upgrade", "pip"], target, log)
        log("安装依赖（首次需要联网，请耐心等待）…")
        pip_base = [python, "-m", "pip", "install", "-r", str(target / "backend" / "requirements.txt")]
        if mirror:
            try:
                run(pip_base + ["-i", MIRROR], target, log)
            except RuntimeError:
                log("镜像安装失败，改用官方 PyPI 重试 …")
                run(pip_base, target, log)
        else:
            run(pip_base, target, log)

    log("初始化数据库与种子数据 …")
    run([python, str(target / "bootstrap.py")], target, log)

    if shortcut:
        log("创建桌面/开始菜单快捷方式 …")
        run([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(target / "scripts" / "create_shortcut.ps1"),
        ], target, log)

    if start:
        pythonw = venv / "Scripts" / "pythonw.exe"
        if not pythonw.exists():
            pythonw = Path(sys.executable).with_name("pythonw.exe")
        log("启动 Guardian-AI …")
        subprocess.Popen(
            [str(pythonw), str(target / "backend" / "desktop" / "launcher.py")],
            cwd=str(target),
            creationflags=NO_WINDOW,
        )
    log("安装完成。")
    log("=" * 52)


def console_install(args) -> int:
    target = Path(args.path).expanduser()
    if not args.yes:
        answer = input(f"将安装到 {target}，继续？[y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    port = args.port
    root_password = args.root_password or secrets.token_urlsafe(12)
    install(
        target,
        port=str(port),
        root_password=root_password,
        mirror=not args.no_mirror,
        shortcut=not args.no_shortcut,
        start=not args.no_start,
        skip_deps=args.skip_deps,
        log=lambda line: print(line, flush=True),
    )
    return 0


def gui_install() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Guardian-AI 安装程序")
    root.geometry("760x650")
    root.minsize(700, 600)

    path_var = tk.StringVar(value=str(default_target()))
    port_var = tk.StringVar(value="8000")
    root_pwd_var = tk.StringVar(value=secrets.token_urlsafe(12))
    mirror_var = tk.BooleanVar(value=True)
    shortcut_var = tk.BooleanVar(value=True)
    start_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="请选择安装位置并填写配置")
    log_queue: queue.Queue[str | None] = queue.Queue()
    busy = {"value": False}

    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    def row(r, label, widget):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=5)
        widget.grid(row=r, column=1, sticky="ew", pady=5)
        return widget

    path_entry = row(0, "安装目录", ttk.Entry(frm, textvariable=path_var))
    ttk.Button(frm, text="浏览…", command=lambda: path_var.set(
        filedialog.askdirectory(initialdir=str(Path(path_var.get()).parent)) or path_var.get()
    )).grid(row=0, column=2, padx=(8, 0))
    row(1, "服务端口", ttk.Entry(frm, textvariable=port_var))
    row(2, "root 初始密码", ttk.Entry(frm, textvariable=root_pwd_var))
    ttk.Label(frm, text="AI 接口（DeepSeek / OpenAI 兼容）在安装完成后登录网页，在 API 页配置。",
              foreground="#64748b").grid(row=3, column=1, sticky="w", pady=(2, 6))
    ttk.Checkbutton(frm, text="使用国内 PyPI 镜像（推荐）", variable=mirror_var).grid(
        row=4, column=1, sticky="w", pady=3)
    ttk.Checkbutton(frm, text="创建桌面和开始菜单快捷方式", variable=shortcut_var).grid(
        row=5, column=1, sticky="w", pady=3)
    ttk.Checkbutton(frm, text="安装完成后启动 Guardian-AI", variable=start_var).grid(
        row=6, column=1, sticky="w", pady=3)

    status = ttk.Label(frm, textvariable=status_var)
    status.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
    install_btn = ttk.Button(frm, text="开始安装")
    install_btn.grid(row=7, column=3, sticky="e", pady=(8, 0))

    ttk.Label(frm, text="安装日志").grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 4))
    log_text = tk.Text(frm, height=10, wrap="word", state="disabled")
    log_text.grid(row=9, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(9, weight=1)
    scroll = ttk.Scrollbar(frm, orient="vertical", command=log_text.yview)
    scroll.grid(row=9, column=3, sticky="ns")
    log_text.configure(yscrollcommand=scroll.set)

    def append_log(line: str) -> None:
        log_text.configure(state="normal")
        log_text.insert("end", line + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")

    def poll() -> None:
        while True:
            try:
                item = log_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            append_log(item)
        root.after(120, poll)

    def worker(target: Path, params: dict) -> None:
        try:
            install(target, log=lambda line: log_queue.put(line), **params)
            log_queue.put("__OK__")
        except Exception as exc:  # noqa: BLE001
            log_queue.put("__ERR__" + str(exc))
            log_queue.put(traceback.format_exc())
        finally:
            busy["value"] = False

    def poll_result() -> None:
        # 单独检查成功/失败标记，避免把标记写进日志
        root.after(300, poll_result)

    def start_install() -> None:
        if busy["value"]:
            return
        raw_path = path_var.get().strip()
        if not raw_path:
            messagebox.showerror("错误", "请填写安装目录")
            return
        target = Path(raw_path).expanduser()
        try:
            port = int(port_var.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "端口必须是 1-65535 的整数")
            return
        if target.exists() and any(target.iterdir()) and target.resolve() != SOURCE.resolve():
            if not messagebox.askyesno("确认", f"目录已存在且不为空：\n{target}\n\n继续将覆盖同名文件，是否继续？"):
                return
        pwd = root_pwd_var.get().strip() or secrets.token_urlsafe(12)
        busy["value"] = True
        install_btn.configure(state="disabled")
        status_var.set("正在安装，请稍候…")
        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.configure(state="disabled")
        params = dict(
            port=str(port),
            root_password=pwd,
            mirror=mirror_var.get(),
            shortcut=shortcut_var.get(),
            start=start_var.get(),
            skip_deps=False,
        )
        threading.Thread(target=worker, args=(target, params), daemon=True).start()

    def poll_flags() -> None:
        # 日志队列中的控制标记
        pass

    # 用轮询同时处理日志和结束标记
    def poll_all() -> None:
        while True:
            try:
                item = log_queue.get_nowait()
            except queue.Empty:
                break
            if item == "__OK__":
                install_btn.configure(state="normal")
                busy["value"] = False
                status_var.set("安装完成")
                messagebox.showinfo("Guardian-AI", "安装完成。\n可双击桌面 Guardian-AI 启动。")
            elif item and item.startswith("__ERR__"):
                install_btn.configure(state="normal")
                busy["value"] = False
                status_var.set("安装失败")
                messagebox.showerror("安装失败", item[len("__ERR__"):])
            elif item:
                append_log(item)
        root.after(120, poll_all)

    install_btn.configure(command=start_install)
    root.after(120, poll_all)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Guardian-AI 安装器")
    parser.add_argument("--path", help="安装目录（提供后使用命令行模式）")
    parser.add_argument("--port", default="8000")
    parser.add_argument("--root-password", default="")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-mirror", action="store_true")
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--skip-deps", action="store_true")
    args = parser.parse_args()
    if args.path:
        return console_install(args)
    return gui_install()


if __name__ == "__main__":
    raise SystemExit(main())
