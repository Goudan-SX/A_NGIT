@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在安装 Python 依赖...
python -m pip install -r backend\requirements.txt
echo.
echo 依赖安装完成。运行 run.bat 启动服务。
pause
