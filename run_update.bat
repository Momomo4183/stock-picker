@echo off
rem Double-click to update the page (dividend stocks, group 2).
rem   fetch prices -> screen -> build page -> push to GitHub
rem When done, the new page opens on this PC. The phone page follows
rem about a minute after the push. Keep this file ASCII only: cmd reads
rem .bat files as cp932 and non-ASCII text can break double-click runs.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
title dividend stocks - update

echo ========================================
echo   dividend stocks - update
echo ========================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -u scripts\update.py %*
set "RET=%errorlevel%"

echo.
if not "%RET%"=="0" (
  echo [NG] exit code %RET%
  echo     Scroll up to see which step failed.
) else (
  echo Opening the page on this PC...
  start "" "%~dp0docs\index.html"
  echo.
  echo Phone: https://momomo4183.github.io/stock-picker/
  echo   The phone page updates about a minute after the push.
)

echo.
echo Press any key to close.
pause >nul
exit /b %RET%
