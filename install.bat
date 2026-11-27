@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 未找到 Python。请安装 Python 3.10 - 3.12（64 位）并勾选 Add to PATH。
    echo 下载地址：https://www.python.org/downloads/windows/
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
  )
  set "PY=python"
)

%PY% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)"
if errorlevel 1 (
  echo [错误] 需要 Python 3.10 - 3.12。当前版本：
  %PY% --version
  pause
  exit /b 1
)

%PY% scripts\install.py
if errorlevel 1 pause
exit /b 0
