# install_teamscout_task.ps1 - register Team Scout as an always-on service.
# Run once (no admin needed): powershell -ExecutionPolicy Bypass -File services\install_teamscout_task.ps1
# Re-running is a no-op if the task already exists. Remove with: Unregister-ScheduledTask -TaskName 'Team Scout'

$ErrorActionPreference = 'Stop'
$wrapper = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'teamscout_service.ps1'

$search = Split-Path -Parent $MyInvocation.MyCommand.Path
while ($search -and -not (Test-Path (Join-Path $search 'PORTS.md'))) {
  $parent = Split-Path -Parent $search
  if ($parent -eq $search) { break }
  $search = $parent
}
. (Join-Path $search 'Scripts\register-web-app-task.ps1')
Register-JamesWebAppTask -TaskName 'Team Scout' -Wrapper $wrapper
