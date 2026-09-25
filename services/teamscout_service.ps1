# teamscout_service.ps1 - keep Team Scout alive on Windows.
# Team Scout binds 127.0.0.1:8324 - James opens it via a browser bookmark, and this
# wrapper's job is to make sure that bookmark never resolves to a dead port.
# Restarts python if it exits. Registered as a Scheduled Task that fires at logon and
# self-heals every 5 minutes (see install_teamscout_task.ps1). Lifecycle
# start/stop/crash goes to logs\teamscout.log.

# this script lives in services\, one level below the repo root
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\teamscout.log'

# Stop-ScheduledTask only kills the headless conhost the task runs under, not
# this wrapper. The shared guard notices, takes this wrapper and its server down,
# and keeps one wrapper per app, so a Stop/Start restart hands over cleanly.
$devRoot = $repo
while ($devRoot -and -not (Test-Path (Join-Path $devRoot 'PORTS.md'))) { $devRoot = Split-Path -Parent $devRoot }
$guard = if ($devRoot) { Join-Path $devRoot 'Scripts\web-app-service-guard.ps1' }
if (-not $guard -or -not (Test-Path $guard)) {
    "$(Get-Date -Format o)  [wrapper] Scripts\web-app-service-guard.ps1 not found above $repo - cannot start" | Out-File -Append -Encoding utf8 $log
    exit 1
}
. $guard
Enter-JamesWebAppService -Name 'Team Scout' -Log $log

# The bare C:\Python314 install (no scout packages) can shadow the interpreter
# this machine actually runs LD2L Scout on. Prefer pythoncore, then py -3.
$python = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe"
if (-not (Test-Path $python)) {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $python = $pyLauncher.Source
        $pythonArgs = @('-3')
    } else {
        $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $pythonCmd) {
            "$(Get-Date -Format o)  [wrapper] python not found - install Python 3, then restart the task" | Out-File -Append -Encoding utf8 $log
            exit 1
        }
        $python = $pythonCmd.Source
        $pythonArgs = @()
    }
} else {
    $pythonArgs = @()
}

Set-Location $repo
# Without this, python's piped stdout is block-buffered and a crash or kill loses
# every line it printed, so the log only ever shows wrapper lifecycle lines.
$env:PYTHONUNBUFFERED = '1'

while ($true) {
    # Stopping the task kills this wrapper but can orphan its python child, which
    # then holds :8324 and EADDRINUSE-loops the next start. Clear it by port;
    # NEVER kill python.exe by name (BBC bots and other scouts also use python).
    Get-NetTCPConnection -LocalPort 8324 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$_" -ErrorAction SilentlyContinue
            if ($p -and ($p.Name -eq 'python.exe' -or $p.Name -eq 'pythonw.exe')) {
                "$(Get-Date -Format o)  [wrapper] killing stray Team Scout python holding :8324 (pid $($p.ProcessId): $($p.CommandLine))" | Out-File -Append -Encoding utf8 $log
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
            } elseif ($p) {
                "$(Get-Date -Format o)  [wrapper] WARNING :8324 is held by $($p.Name) (pid $($p.ProcessId)) - not ours, leaving it alone; Team Scout will fail to bind" | Out-File -Append -Encoding utf8 $log
            }
        }
    "$(Get-Date -Format o)  [wrapper] starting Team Scout ($python ld2l_scout.py --teamscout --offline --no-browser --auto-refresh)" | Out-File -Append -Encoding utf8 $log
    & $python @pythonArgs ld2l_scout.py --teamscout --offline --no-browser --auto-refresh 2>&1 | Out-File -Append -Encoding utf8 $log
    Exit-JamesWebAppServiceIfConsoleLost $LASTEXITCODE
    "$(Get-Date -Format o)  [wrapper] Team Scout exited (code $LASTEXITCODE) - restarting in 15s" | Out-File -Append -Encoding utf8 $log
    Start-Sleep -Seconds 15
}
