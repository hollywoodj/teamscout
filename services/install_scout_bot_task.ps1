# install_scout_bot_task.ps1 - register the Scout Bot Discord gateway as an
# always-on service.
# Run once (no admin needed): powershell -ExecutionPolicy Bypass -File services\install_scout_bot_task.ps1
# Re-running just updates the task (unless it's already S4U - see below).
# Remove with: Unregister-ScheduledTask -TaskName 'Scout Bot'

$ErrorActionPreference = 'Stop'
# wrapper is a sibling of this installer in services\
$wrapper = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'scout_bot_service.ps1'
$taskName = 'Scout Bot'

# Never -Force replace an existing S4U task - leave it. (Dev/CLAUDE.md,
# "Claiming a port" / "Local web apps are always-on services" standard.)
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Principal.LogonType -eq 'S4U') {
    Write-Output "Scheduled task '$taskName' is already registered with S4U logon - leaving it in place."
    Write-Output "Start now:  Start-ScheduledTask -TaskName '$taskName'"
    exit 0
}

# conhost --headless wrapping a fully-qualified powershell.exe: with Windows
# Terminal as the default console host, a bare `powershell.exe -WindowStyle
# Hidden` target still opens a visible Terminal window for as long as the
# wrapper runs (see Dev/CLAUDE.md "No incidental terminal windows"). This
# applies to BOTH the S4U and the Interactive-fallback principal below -
# S4U runs outside the interactive desktop, but the fallback is used
# precisely when S4U isn't available (interactive session), where the
# Terminal-window problem is real.
$powershellExe = (Get-Command powershell.exe).Source
$conhostExe = Join-Path $env:WINDIR 'System32\conhost.exe'
$action = New-ScheduledTaskAction -Execute $conhostExe `
    -Argument "--headless `"$powershellExe`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`""

# At-logon covers a cold start (the box has just booted / James has just
# logged in); the 5-minute indefinite repeat covers a mid-uptime death the
# same way the other BBC service tasks do. Scout Bot keeps both per this
# project's local-web-app-adjacent service standard.
# Scoped to this user: an any-user AtLogOn trigger needs admin and is what
# makes registration fail with 0x80070005 under both S4U and Interactive.
$loginTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$healTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

try {
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $loginTrigger, $healTrigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output "Registered scheduled task '$taskName' with S4U logon for $env:USERNAME."
} catch {
    # ErrorActionPreference=Stop turns the cmdlet's terminating CimException
    # into this catch; the HRESULT shows up in FullyQualifiedErrorId (and
    # usually CategoryInfo), not reliably in Exception.Message, so check both.
    $isAccessDenied = $_.FullyQualifiedErrorId -match '0x80070005' -or
                       $_.Exception.Message -match '0x80070005' -or
                       ($_.Exception.InnerException -and $_.Exception.InnerException.Message -match '0x80070005') -or
                       "$($_.CategoryInfo)" -match 'PermissionDenied'
    if (-not $isAccessDenied) {
        throw
    }
    Write-Output "S4U registration denied (0x80070005) on this machine - falling back to Interactive."
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $loginTrigger, $healTrigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output "Registered scheduled task '$taskName' with Interactive logon for $env:USERNAME."
}

Write-Output "Start now:  Start-ScheduledTask -TaskName '$taskName'"
Write-Output "Stop:       Disable-ScheduledTask -TaskName '$taskName'  (a plain stop is undone by the 5-min repeat)"
Write-Output "Resume:     Enable-ScheduledTask  -TaskName '$taskName'"
Write-Output "Remove:     Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
