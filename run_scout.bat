@echo off
REM LD2L Scout - Runner
REM
REM   run_scout.bat         Visible run: live output on screen, also appended to
REM                         scout_log.txt, window stays open at the end.
REM   run_scout.bat quiet   Silent run: log only. Used by the Task Scheduler job
REM                         "LD2L Scout Refresh", which runs every 2 hours.
REM
REM Output filenames are derived from the season (e.g. LD2L_S22_Scouting.xlsx)

cd /d "%~dp0"

if /i "%~1"=="quiet" goto quiet

REM UTF-8 so the emoji in the output render instead of turning into mojibake.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scout_tee.ps1" "%~dp0scout_log.txt" "%~dp0ld2l_scout.py"
echo.
echo Exit code: %errorlevel%
pause
goto :eof

:quiet
python ld2l_scout.py >> "%~dp0scout_log.txt" 2>&1
exit /b %errorlevel%
