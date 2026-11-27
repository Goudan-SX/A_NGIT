@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 5; Write-Host '后端正常：' $r.StatusCode; $r.Content } catch { Write-Host '后端未运行或启动失败：' $_.Exception.Message }"
echo.
echo 服务地址：http://127.0.0.1:8000/
pause
