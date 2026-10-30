$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
function Assert-Idle {
    $state = Invoke-RestMethod http://127.0.0.1:5002/state -TimeoutSec 5
    $agent = Invoke-RestMethod http://127.0.0.1:5002/researcher/api/lacry/state -TimeoutSec 5
    $hamilton = Invoke-RestMethod http://127.0.0.1:5002/researcher/api/lacry/hamilton/status -TimeoutSec 5
    $researcher = Invoke-RestMethod http://127.0.0.1:5002/researcher/api/status -TimeoutSec 5
    if ($state.robot.connected -or $state.sequence.active -or $agent.busy -or $agent.running.active -or $agent.pending -or $hamilton.state -ne 'idle' -or $researcher.hand_guiding.active) {
        throw 'Reload deferred: require disconnected robot and idle lab workflows.'
    }
    return $state
}
$before = Assert-Idle
$listener = Get-NetTCPConnection -LocalPort 5002 -State Listen
$consoleProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if ($consoleProcess.CommandLine -notmatch 'operator_ui[/\\]app\.py') { throw 'Unexpected console process.' }
$pythonPath = $consoleProcess.ExecutablePath
$null = Invoke-RestMethod http://127.0.0.1:5002/developer/api/dsl/diagnostic -TimeoutSec 5
$null = Assert-Idle
$null = Invoke-RestMethod http://127.0.0.1:5002/camera/release -Method Post -ContentType 'application/json' -Body '{}'
Stop-Process -Id $consoleProcess.ProcessId
Start-Sleep -Milliseconds 700
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$started = Start-Process -FilePath $pythonPath -ArgumentList '-B','-u','operator_ui/app.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot/devin_reload_$stamp.stdout.log" -RedirectStandardError "$PSScriptRoot/devin_reload_$stamp.stderr.log"
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 300
    try {
        $check = Invoke-RestMethod http://127.0.0.1:5002/developer/api/dsl/devin -TimeoutSec 2
        if (-not $before.camera.enabled) {
            $null = Invoke-RestMethod http://127.0.0.1:5002/camera/release -Method Post -ContentType 'application/json' -Body '{}'
        }
        Write-Output "Developer backend loaded, PID $($started.Id); Devin available: $($check.available). No motion commands sent."
        exit 0
    } catch { if ($started.HasExited) { throw 'Flask exited; inspect devin_reload stderr log.' } }
}
throw 'Updated Flask endpoint did not become available; inspect devin_reload logs.'
