@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
title stock picker - update

echo ========================================
echo   stock picker - update
echo ========================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -u scripts\update.py %*
set "RET=%errorlevel%"

echo.
if not "%RET%"=="0" echo [NG] exit code %RET%
exit /b %RET%
