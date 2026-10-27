$ErrorActionPreference = 'Stop'
$uiRoot = Split-Path $PSScriptRoot -Parent
$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -match 'capture_next_lacry_calibration\.py' }
if ($existing) { throw 'A calibration capture is already running.' }
$pythonPath = (Resolve-Path "$uiRoot/../.venv-realsense/Scripts/python.exe").Path
$capture = Start-Process -FilePath $pythonPath -ArgumentList '-B','-u','reports/hamilton_connection/capture_next_lacry_calibration.py' -WorkingDirectory $uiRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot/hamilton_connection/next_capture.stdout.log" -RedirectStandardError "$PSScriptRoot/hamilton_connection/next_capture.stderr.log"
Write-Output "Passive calibration capture started, PID $($capture.Id). No hardware write commands."
