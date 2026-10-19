# Starts the Downloads watcher hidden in the background every time you log in to Windows (and right now).
# It waits for emploi_du_temps*.pdf in your Downloads folder, then syncs Google Calendar and emails you.
# Usage (PowerShell, in this folder):   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
# Remove it later:                      Unregister-ScheduledTask -TaskName "ESPRIT EDT watcher" -Confirm:$false

$dir  = $PSScriptRoot
$name = "ESPRIT EDT watcher"

# Find pythonw.exe (same Python as "python", but without a console window)
$py  = (& python -c "import sys; print(sys.executable)").Trim()
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

# Remove the old weekly task from the previous version, if it exists
Unregister-ScheduledTask -TaskName "ESPRIT EDT sync" -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dir\main.py`" --watch" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
              -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
  -Description "Watches Downloads for the ESPRIT timetable PDF, syncs Google Calendar, emails the PDF" -Force | Out-Null
Start-ScheduledTask -TaskName $name

Write-Host "OK: '$name' is running now and will start at every logon."
Write-Host "Download your timetable PDF, then check logs\watch.log"
