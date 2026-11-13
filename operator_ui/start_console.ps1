$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$consolePython = Join-Path $projectRoot '.venv-realsense\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $consolePython)) { throw 'Run operator_ui/setup_realsense.ps1 first.' }
Push-Location $projectRoot
try {
    & $consolePython -B -u operator_ui/app.py
    if ($LASTEXITCODE) { throw "Console exited with code $LASTEXITCODE" }
} finally { Pop-Location }
