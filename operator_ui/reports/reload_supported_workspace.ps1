param([switch]$ArmAndPlateSupported)
$ErrorActionPreference = 'Stop'
if (-not $ArmAndPlateSupported) { throw 'Requires current operator confirmation: arm and plate supported, E-stop supervised.' }
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$base = 'http://127.0.0.1:5002'
$before = Invoke-RestMethod "$base/state" -TimeoutSec 5
$researcher = Invoke-RestMethod "$base/researcher/api/status" -TimeoutSec 5
if ($before.sequence.active -or -not $before.robot.ok -or -not $before.robot.connected -or $before.robot.errors.Count -or $before.robot.program_state.state -ne 'stopped' -or $before.robot.control_mode.mode -ne 'manual' -or $researcher.hand_guiding.state -ne 'active') {
    throw 'Expected healthy stopped program and active manual hand-guiding, with no sequence.'
}
$latch = Join-Path $projectRoot 'operator_ui/demonstrations/draggo-active.json'
if (-not (Test-Path -LiteralPath $latch)) { throw 'Hand-guiding latch missing; do not reload.' }
$listener = Get-NetTCPConnection -LocalPort 5002 -State Listen
$consoleProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if ($consoleProcess.CommandLine -notmatch 'operator_ui[/\\]app\.py') { throw 'Unexpected console process.' }
$second = Invoke-RestMethod "$base/state" -TimeoutSec 5
if ($second.sequence.active -or -not $second.robot.ok -or $second.robot.errors.Count -or $second.robot.program_state.state -ne 'stopped' -or $second.robot.control_mode.mode -ne 'manual') { throw 'Controller state changed; reload deferred.' }
foreach ($axis in @('X','Y','Z','Rz')) {
    if ([Math]::Abs($second.robot.pose_mm.$axis - $before.robot.pose_mm.$axis) -gt 0.05) { throw 'Arm is moving; reload deferred.' }
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$record = Join-Path $PSScriptRoot "squid/workspace_reload_$stamp.json"
@{before=$before; researcher_before=$researcher; audit_before=(Invoke-RestMethod "$base/audit/status" -TimeoutSec 5); operator_confirmation='Arm and plate supported; E-stop supervised; reload requested'; old_process=$consoleProcess.ProcessId} | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $record -Encoding UTF8
# Supported hand-guiding reload: preserve its latch and native controller mode.
# Do not call disable, program start/stop, DragGo, gripper or movement endpoints.
# Ending the Flask process closes its sockets; the standalone recorder stays up.
Stop-Process -Id $consoleProcess.ProcessId
Wait-Process -Id $consoleProcess.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
$started = Start-Process -FilePath $consoleProcess.ExecutablePath -ArgumentList '-B','-u','operator_ui/app.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot/squid/workspace_reload_$stamp.stdout.log" -RedirectStandardError "$PSScriptRoot/squid/workspace_reload_$stamp.stderr.log"
$ready = $false
for ($attempt=0; $attempt -lt 20; $attempt++) {
    try { $params = Invoke-RestMethod "$base/robot_params" -TimeoutSec 2; $ready=$true; break } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready) { throw 'Console did not restart. Keep arm supported; inspect reload log.' }
$connected = Invoke-RestMethod "$base/researcher/api/connect" -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 10
if (-not $connected.ok) { throw 'Console restarted but reconnect failed; keep arm supported.' }
$after = Invoke-RestMethod "$base/state" -TimeoutSec 5
$researcherAfter = Invoke-RestMethod "$base/researcher/api/status" -TimeoutSec 5
$reach = $params.link1_mm + $params.link2_mm - $params.extension_margin_mm - 2
@{after=$after; researcher_after=$researcherAfter; new_process=$started.Id; automatic_reach_mm=$reach; motion_commands_sent=$false} | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath "$PSScriptRoot/squid/workspace_reload_${stamp}_after.json" -Encoding UTF8
if (-not $after.robot.ok -or $after.robot.errors.Count -or $after.robot.program_state.state -ne 'stopped' -or $after.robot.control_mode.mode -ne 'manual' -or $researcherAfter.hand_guiding.state -ne 'active') { throw 'Unexpected controller state after reload; keep arm supported and inspect saved status.' }
if ($after.envelope.Y.max -ne 380 -or -not $after.envelope.enabled -or $reach -ne 390) { throw 'Requested limits did not load.' }
Write-Output "Reload complete. PID $($started.Id); Y max 380 mm, automatic reach 390 mm. Manual hand-guiding active; program stopped; no motion commands. Evidence: $record"
