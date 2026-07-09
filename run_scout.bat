@echo off
REM LD2L Scout - Background Runner
REM This gets called by Task Scheduler every 2 hours
REM Output filenames are derived from the season (e.g. LD2L_S22_Scouting.xlsx)

cd /d "%~dp0"
python ld2l_scout.py >> "%~dp0scout_log.txt" 2>&1
