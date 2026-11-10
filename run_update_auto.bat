@echo off
rem Unattended version of run_update.bat for Task Scheduler (weekdays 12:00).
rem   Same update (fetch prices -> screen -> build page -> push to GitHub),
rem   but no page opening and no "press any key". Output goes to
rem   logs\update_auto.log. Added 2026-11-10.
rem   The trader re-checks the market at 12:30, so 12:00 leaves ~30 min.
rem Keep this file ASCII only (cmd reads .bat as cp932).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist logs mkdir logs
set "LOG=logs\update_auto.log"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo.>> "%LOG%"
echo ==== start %date% %time% ====>> "%LOG%"
rem --no-fund: skip the weekly fundamentals refetch (slow, many requests) so the
rem run ends well before 12:30. Manual runs (run_update.bat) still refetch weekly.
%PY% -u scripts\update.py --no-fund %* >> "%LOG%" 2>&1
set "RET=%errorlevel%"
echo ==== end %date% %time% exit=%RET% ====>> "%LOG%"
exit /b %RET%
