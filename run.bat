@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动反诈卫士后端...
echo 浏览器访问：http://127.0.0.1:8000/
python backend\run.py
pause
