<#
  Runs the scout and writes every line it produces to both the console and the
  log, so a manual run is watchable while still leaving behind the same record
  the scheduled run leaves.

  Called by run_scout.bat; not meant to be run on its own.

  Note: python is launched via "cmd /c ... 2>&1" so stdout and stderr arrive
  already merged on one stream. Reading two streams from here instead risks
  deadlocking when one of them fills its buffer, and PowerShell 5.1 would also
  wrap every stderr line in an ErrorRecord.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$LogPath,

    [Parameter(Mandatory = $true)]
    [string]$ScriptPath
)

$utf8 = New-Object System.Text.UTF8Encoding $false

# Emoji in the output only render correctly if the console agrees it is UTF-8.
try { [Console]::OutputEncoding = $utf8 } catch { }

# LD2L Scout's --live mode needs python-socketio 4.x (LD2L's site runs
# socket.io v2); BBC's Control Room server needs 5.x on the same machine-wide
# Python 3.14, and both 3.14 installs share one per-user site-packages dir. A
# repo-local .venv keeps LD2L Scout's pins isolated so a bare "python" call
# below resolves to it. Falls back to PATH's own python if .venv is absent
# (e.g. a fresh clone that hasn't been set up yet).
$venvScripts = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '.venv\Scripts'
if (Test-Path (Join-Path $venvScripts 'python.exe')) {
    $env:PATH = "$venvScripts;$env:PATH"
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'cmd.exe'
# -u keeps progress flushing live instead of buffering until the run ends.
$psi.Arguments = '/c python -u "' + $ScriptPath + '" 2>&1'
$psi.WorkingDirectory = Split-Path -Parent $ScriptPath
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.StandardOutputEncoding = $utf8

# No BOM: scout_log.txt is plain UTF-8 and is appended to, never rewritten.
$writer = New-Object System.IO.StreamWriter $LogPath, $true, $utf8
# Flush per line so a run that is cancelled or crashes still leaves a full log.
$writer.AutoFlush = $true

try {
    $proc = [System.Diagnostics.Process]::Start($psi)
    while ($null -ne ($line = $proc.StandardOutput.ReadLine())) {
        Write-Host $line
        $writer.WriteLine($line)
    }
    $proc.WaitForExit()
    $exitCode = $proc.ExitCode
}
finally {
    $writer.Dispose()
}

exit $exitCode
