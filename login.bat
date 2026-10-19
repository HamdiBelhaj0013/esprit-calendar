@echo off
rem Log in to ESPRIT once (a browser window opens: tick the captcha, click "Se connecter").
rem The session is saved, then the timetable sync runs right away.
cd /d "%~dp0"
python fetch_edt.py --login
if errorlevel 1 (
  echo.
  echo Login failed - try again.
  pause
  exit /b 1
)
echo.
echo Syncing the timetable...
call run_edt.bat
type logs\last_run.log
pause
