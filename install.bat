@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Guardian-AI 安装程序
echo ============================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 未找到 Python。请安装 Python 3.10 - 3.12（64 位）并勾选 Add to PATH。
    echo 下载：https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
  set "PY=python"
)

%PY% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)"
if errorlevel 1 (
  echo [错误] 需要 Python 3.10 - 3.12（当前版本不兼容部分依赖）。
  %PY% --version
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] 创建虚拟环境 .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
  )
) else (
  echo [1/4] 已存在虚拟环境 .venv
)

echo [2/4] 安装 Python 依赖（首次需要联网，可能较慢）...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :deps_fail
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 goto :deps_fail

echo [3/4] 初始化数据库...
".venv\Scripts\python.exe" bootstrap.py
if errorlevel 1 (
  echo [错误] 数据库初始化失败，请检查 SQL Server LocalDB 与 ODBC 驱动。
  pause
  exit /b 1
)

echo [4/4] 创建桌面快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\create_shortcut.ps1"
if errorlevel 1 (
  echo [警告] 快捷方式创建失败，可直接双击 start.bat 启动。
)

echo.
echo 安装完成。双击桌面 Guardian-AI，或运行 start.bat 启动。
echo 首次启动如弹出 UAC，请选择“是”（本地聊天监测需要）。
echo.
choice /C YN /M "是否现在启动 Guardian-AI"
if errorlevel 2 goto :done
call start.bat
:done
pause
exit /b 0

:deps_fail
echo.
echo [错误] 依赖安装失败。可尝试使用国内镜像：
echo   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
pause
exit /b 1
