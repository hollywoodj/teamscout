# LD2L Scout - Task Scheduler Installer
# Run this ONCE as Administrator to set up the background job
# Right-click > Run with PowerShell (as Admin)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $scriptDir "run_scout.bat"
$taskName = "LD2L_Scout_AutoUpdate"

# Check if bat exists
if (-not (Test-Path $batPath)) {
    Write-Host "ERROR: run_scout.bat not found in $scriptDir" -ForegroundColor Red
    Write-Host "Make sure run_scout.bat and ld2l_scout.py are in the same folder."
    pause
    exit 1
}

# Remove existing task if it exists
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Build the task
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Days 365)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Register it
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "LD2L S21 Scouting - Auto-updates player data every 2 hours" -RunLevel Highest

# Run it immediately
Start-ScheduledTask -TaskName $taskName

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  LD2L Scout installed successfully!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Task: $taskName"
Write-Host "  Runs: Every 2 hours (started now)"
Write-Host "  Log:  $scriptDir\scout_log.txt"
Write-Host "  XLSX: $scriptDir\LD2L_S21_Scouting.xlsx"
Write-Host ""
Write-Host "  To stop:  Run uninstall_scout.ps1"
Write-Host "  To check: Open Task Scheduler > $taskName"
Write-Host ""
pause
