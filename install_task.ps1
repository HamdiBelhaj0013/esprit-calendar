# Creates a Windows scheduled task: every Sunday at 20:00, run run_edt.bat.
# If the PC is off or asleep at that time, it runs as soon as the PC is back on (and online).
# Usage (PowerShell, in this folder):   powershell -ExecutionPolicy Bypass -File .\install_task.ps1

$dir = $PSScriptRoot
$name = "ESPRIT EDT sync"

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$dir\run_edt.bat`"" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "20:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
              -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
  -Description "Downloads the ESPRIT timetable, syncs Google Calendar, emails the PDF" -Force | Out-Null

Write-Host "Scheduled task '$name' created: every Sunday 20:00 (or at next startup if the PC was off)."
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$name'   then check logs\last_run.log"
