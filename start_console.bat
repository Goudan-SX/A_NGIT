@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在以控制台模式启动 Guardian-AI 后端（便于查看报错）...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" backend\run.py
) else (
  python backend\run.py
)
pause
