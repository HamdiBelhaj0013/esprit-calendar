@echo off
rem Runs the weekly sync. Used by the scheduled task, but you can also double-click it.
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% ===== > logs\last_run.log
python main.py >> logs\last_run.log 2>&1
if errorlevel 1 (
  echo FAILED - see logs\last_run.log >> logs\last_run.log
  exit /b 1
)
