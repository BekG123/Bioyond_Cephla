param([switch]$ArmAndPlateSupported)
& ../.venv-realsense/Scripts/python.exe -B reports/hamilton_connection/preserve_unverified_calibration.py
if ($LASTEXITCODE -ne 0) { throw 'Native-finished evidence check failed; reload refused.' }
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$before = Invoke-RestMethod http://127.0.0.1:5002/state -TimeoutSec 5
$researcher = Invoke-RestMethod http://127.0.0.1:5002/researcher/api/status -TimeoutSec 5
$stoppedDisabled = $before.robot.program_state.state -eq 'stopped' -and $before.robot.enabled -eq $false
$supportedPausedManual = $ArmAndPlateSupported -and $before.robot.control_mode.mode -eq 'manual' -and $before.robot.program_state.state -eq 'paused'
if (($before.sequence.active -and $before.sequence.name -ne 'lacry_hamilton') -or $researcher.hand_guiding.state -ne 'off' -or ($before.robot.control_mode.mode -ne 'auto' -and -not $stoppedDisabled -and -not $supportedPausedManual) -or -not $before.robot.ok -or $before.robot.errors.Count) {
    throw 'Reload deferred: require idle sequence, healthy controller and hand-guiding off.'
}
Start-Sleep -Milliseconds 500
$second = Invoke-RestMethod http://127.0.0.1:5002/state -TimeoutSec 5
if ($second.sequence.active -and $second.sequence.name -ne 'lacry_hamilton') { throw 'Another sequence started; reload deferred.' }
if (-not $second.robot.ok -or $second.robot.errors.Count -or $second.robot.control_mode.mode -ne $before.robot.control_mode.mode -or $second.robot.program_state.state -ne $before.robot.program_state.state) { throw 'Controller state changed; reload deferred.' }
foreach ($axis in @('X','Y','Z','Rz')) {
    if ([Math]::Abs($second.robot.pose_mm.$axis - $before.robot.pose_mm.$axis) -gt 0.05) { throw 'Arm is moving; reload deferred.' }
}
$listener = Get-NetTCPConnection -LocalPort 5002 -State Listen
$consoleProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if ($consoleProcess.CommandLine -notmatch 'operator_ui[/\\]app\.py') { throw 'Unexpected console process.' }
$pythonPath = $consoleProcess.ExecutablePath
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$trial = @{state=$before; sequence=(Invoke-RestMethod http://127.0.0.1:5002/seq -TimeoutSec 5); researcher=$researcher; arm_and_plate_supported_confirmation=[bool]$ArmAndPlateSupported}
$trial | ConvertTo-Json -Depth 35 | Set-Content -Encoding UTF8 -LiteralPath "$PSScriptRoot/corrected_descent_reload_$stamp.json"
$before | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 -LiteralPath "$PSScriptRoot/corrected_descent_before_reload.json"
# The stale sequence owns these HTTP controls, so they correctly refuse a
# resource-release call. After the exact native-finished check above, process
# termination releases the idle app's camera and sockets. No device commands.
Stop-Process -Id $consoleProcess.ProcessId
Start-Sleep -Milliseconds 700
$started = Start-Process -FilePath $pythonPath -ArgumentList '-B','-u','operator_ui/app.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$projectRoot/operator_ui/corrected_descent_console.stdout.log" -RedirectStandardError "$projectRoot/operator_ui/corrected_descent_console.stderr.log"
Write-Output "Loaded updated console backend, PID $($started.Id). No motion commands sent."
