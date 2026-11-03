param(
    [switch]$StageClearAndArmHome,
    [switch]$PreviewOnly,
    [switch]$RealCamera,
    [string]$SoftwarePath = (Join-Path $env:USERPROFILE 'Desktop\squid-latest\software'),
    [string]$PythonPath = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe')
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$SoftwarePath = (Resolve-Path -LiteralPath $SoftwarePath).Path
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$bridgePath = Join-Path $projectRoot 'operator_ui\squid_bridge\launch.py'
if (-not (Test-Path -LiteralPath (Join-Path $SoftwarePath 'main_hcs.py'))) {
    throw 'Selected Squid installation has no main_hcs.py. No alternate installation was selected.'
}
$cameraArguments = @('--stage-only','--simulate-camera')
if ($RealCamera) { $cameraArguments = @('--require-real-camera') }
if ($PreviewOnly) {
    & $PythonPath -B $bridgePath --software $SoftwarePath @cameraArguments --controller-serial 12769210 --start-server --check
    exit $LASTEXITCODE
}
if (-not $StageClearAndArmHome) { throw 'Operator clearance for startup homing is required.' }
# A native Squid may be running with its MCP server off. Do not start a second GUI.
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'main_hcs\.py|squid_bridge[\\/]launch\.py'
}
if ($existing) { throw 'Close the existing Squid normally first. No process was stopped.' }
$state = Invoke-RestMethod http://127.0.0.1:5002/state -TimeoutSec 5
if ($state.sequence.active -or -not $state.robot.ok -or $state.robot.errors.Count) {
    throw 'Require an idle healthy arm before Squid startup.'
}
if (-not $state.robot.connected -or -not $state.robot.pose_mm) {
    throw 'A live connected arm pose is required to verify Home before Squid startup.'
}
$homeTarget = @{ X=289.97; Y=62.63; Z=248.02; Rz=-3.88 }
foreach ($axis in $homeTarget.Keys) {
    if ([Math]::Abs($state.robot.pose_mm.$axis - $homeTarget[$axis]) -gt 0.2) {
        throw 'Arm must remain at Home, clear of the microscope.'
    }
}
if (Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Close Squid normally before starting the updated add-on. No process was stopped.'
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$arguments = @('-B','-u',('"{0}"' -f $bridgePath),'--software',('"{0}"' -f $SoftwarePath),
    '--controller-serial','12769210','--start-server') + $cameraArguments
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $softwarePath `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$projectRoot\operator_ui\reports\squid_connection\lifecycle_$stamp.stdout.log" `
    -RedirectStandardError "$projectRoot\operator_ui\reports\squid_connection\lifecycle_$stamp.stderr.log"
Write-Output "Started updated Squid add-on, PID $($process.Id). Native startup homing is expected. No robot or acquisition command was sent."
Write-Output "Squid source: $SoftwarePath. Physical XYZ stage; real camera requested: $RealCamera."
