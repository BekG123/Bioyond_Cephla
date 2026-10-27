param([switch]$StageClearAndArmHome)
$ErrorActionPreference = 'Stop'
if (-not $StageClearAndArmHome) { throw 'Operator clearance for startup homing is required.' }
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$state = Invoke-RestMethod http://127.0.0.1:5002/state -TimeoutSec 5
if ($state.sequence.active -or -not $state.robot.ok -or $state.robot.errors.Count) {
    throw 'Require an idle healthy arm before Squid startup.'
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
$softwarePath = 'C:\Users\Cephla\AppData\Local\Temp\claude\squid-latest\software'
$pythonPath = 'C:\Users\Cephla\AppData\Local\Programs\Python\Python310\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$arguments = @('-B','-u',"$projectRoot\operator_ui\squid_bridge\launch.py",'--software',$softwarePath,
    '--stage-only','--simulate-camera','--controller-serial','12769210','--start-server')
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $softwarePath `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$projectRoot\operator_ui\reports\squid_connection\lifecycle_$stamp.stdout.log" `
    -RedirectStandardError "$projectRoot\operator_ui\reports\squid_connection\lifecycle_$stamp.stderr.log"
Write-Output "Started updated Squid add-on, PID $($process.Id). Native startup homing is expected. No robot or acquisition command was sent."
