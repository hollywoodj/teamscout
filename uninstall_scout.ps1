# LD2L Scout - Task Scheduler Uninstaller
# Right-click > Run with PowerShell (as Admin)

$taskName = "LD2L_Scout_AutoUpdate"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task '$taskName' removed." -ForegroundColor Green
} else {
    Write-Host "Task '$taskName' not found - nothing to remove." -ForegroundColor Yellow
}

pause
