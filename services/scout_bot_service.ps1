# scout_bot_service.ps1 - keep the Scout Bot Discord gateway alive on Windows.
# Registered as a Scheduled Task that fires at logon + a 5-minute self-heal
# repeat (see install_scout_bot_task.ps1). Runs `python scout_bot.py`
# (no args - the always-on gateway path, never --post-briefing or
# --sync-hero-emojis) from the repo root and restarts it if it exits.
# The bot logs to logs\scout_bot.log itself; this wrapper only records
# start/stop/crash lifecycle to logs\scout_bot_service.log.

# this script lives in services\, one level below the repo root
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\scout_bot_service.log'

# The bare C:\Python314 install (no show packages) shadows the real interpreter
# on the machine PATH, so prefer the pythoncore install the show runs on.
$python = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe"
if (-not (Test-Path $python)) { $python = 'python' }

# Stopping the Scheduled Task can orphan its Python child. Clear only a
# stale gateway instance of scout_bot.py before entering the relaunch loop -
# never touch a `--post-briefing` or `--sync-hero-emojis` one-shot run,
# those are unrelated CLI invocations that happen to share the same script.
# Also catches a stale instance still running from the old BBC checkout
# (BBC\bots\scout_bot.py) left over from before the move to this repo.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like 'python*' -and
        $_.CommandLine -match 'scout_bot\.py' -and
        $_.CommandLine -notmatch '--post-briefing|--sync-hero-emojis'
    } |
    ForEach-Object {
        "$(Get-Date -Format o)  [wrapper] killing stale scout_bot pid $($_.ProcessId) before restart" | Out-File -Append -Encoding utf8 $log
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }

while ($true) {
    "$(Get-Date -Format o)  [wrapper] starting scout bot ($python)" | Out-File -Append -Encoding utf8 $log
    & $python scout_bot.py 2>&1 | Out-File -Append -Encoding utf8 $log
    "$(Get-Date -Format o)  [wrapper] scout bot exited (code $LASTEXITCODE) - restarting in 15s" | Out-File -Append -Encoding utf8 $log
    Start-Sleep -Seconds 15
}
