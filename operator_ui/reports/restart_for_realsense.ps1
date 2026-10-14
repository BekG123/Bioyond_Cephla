# Reload the updated console only while the existing robot program is stopped.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$state = Invoke-RestMethod http://127.0.0.1:5002/state -TimeoutSec 5
if ($state.sequence.active -or $state.robot.program_state.state -ne 'stopped') {
    throw 'Console restart deferred: robot program must already be stopped, with no sequence active.'
}
$listener = Get-NetTCPConnection -LocalPort 5002 -State Listen
$consoleProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if ($consoleProcess.CommandLine -notmatch 'operator_ui[/\\]app\.py') {
    throw 'Unexpected process owns port 5002; refusing to stop it.'
}
$pythonPath = $consoleProcess.ExecutablePath
$released = Invoke-RestMethod http://127.0.0.1:5002/camera/release -Method Post -ContentType 'application/json' -Body '{}'
$disconnected = Invoke-RestMethod http://127.0.0.1:5002/disconnect -Method Post -ContentType 'application/json' -Body '{}'
if ($disconnected.ok -eq $false) { throw 'Robot connection was not released' }
Stop-Process -Id $consoleProcess.ProcessId
Start-Sleep -Milliseconds 700
$started = Start-Process -FilePath $pythonPath -ArgumentList '-B','-u','operator_ui/app.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$projectRoot/operator_ui/realsense_console.stdout.log" -RedirectStandardError "$projectRoot/operator_ui/realsense_console.stderr.log"
Write-Output "Updated console PID: $($started.Id). Robot remains disconnected; no motion commanded."
