@echo off
REM LD2L Scout - Background Runner
REM This gets called by Task Scheduler every 2 hours

cd /d "%~dp0"
python ld2l_scout.py --output "%~dp0LD2L_S21_Scouting.xlsx" >> "%~dp0scout_log.txt" 2>&1
