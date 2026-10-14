$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not (Test-Path 'third_party/mjviser/.git')) {
        git clone https://github.com/mujocolab/mjviser.git third_party/mjviser
        if ($LASTEXITCODE) { throw 'mjviser clone failed' }
        git -C third_party/mjviser checkout ae0b219a2049a95e1321214e4efd1d395ee4bf39
        if ($LASTEXITCODE) { throw 'mjviser checkout failed' }
    }
    if (-not (Test-Path '.venv-realsense/Scripts/python.exe')) {
        py -3.10 -m venv .venv-realsense
        if ($LASTEXITCODE) { throw 'Environment creation failed' }
    }
    & .venv-realsense/Scripts/python.exe -m pip --isolated install --upgrade pip
    if ($LASTEXITCODE) { throw 'pip update failed' }
    & .venv-realsense/Scripts/python.exe -m pip --isolated install -r operator_ui/requirements-realsense.txt
    if ($LASTEXITCODE) { throw 'Dependency install failed' }
    & .venv-realsense/Scripts/python.exe -m pip check
    if ($LASTEXITCODE) { throw 'Dependency check failed' }
    Write-Host 'Ready. Start the Flask console and open D405 Depth.'
} finally { Pop-Location }
