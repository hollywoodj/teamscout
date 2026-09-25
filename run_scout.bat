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

REM LD2L Scout's --live mode needs python-socketio 4.x (LD2L's site runs
REM socket.io v2); BBC's Control Room server needs 5.x on the same machine-wide
REM Python 3.14. Both 3.14 installs share one per-user site-packages dir, so a
REM machine-wide install of the 4.x pair would shadow BBC's 5.x. A repo-local
REM .venv keeps LD2L Scout's pins isolated. Fall back to bare "python" (PATH)
REM if .venv hasn't been created yet, e.g. on a fresh clone.
if exist "%~dp0.venv\Scripts\python.exe" set "PATH=%~dp0.venv\Scripts;%PATH%"

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
