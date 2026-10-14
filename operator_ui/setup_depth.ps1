# Run from any directory. Installs only the local depth environment.
$ErrorActionPreference = 'Stop'
$depthRoot = Split-Path -Parent $PSScriptRoot
Set-Location $depthRoot
if (-not (Test-Path 'third_party/Depth-Anything-V2/.git')) {
    git clone https://github.com/DepthAnything/Depth-Anything-V2.git third_party/Depth-Anything-V2
    if ($LASTEXITCODE) { throw 'Clone failed' }
}
git -C third_party/Depth-Anything-V2 checkout a561b849ebae10a6f5ef49e26c83cbbcd36c71bf
if ($LASTEXITCODE) { throw 'Source checkout failed' }
if (-not (Test-Path '.venv-depth/Scripts/python.exe')) {
    py -m venv --system-site-packages .venv-depth
    if ($LASTEXITCODE) { throw 'Environment creation failed' }
}
& .venv-depth/Scripts/python.exe -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu126
if ($LASTEXITCODE) { throw 'PyTorch installation failed' }
& .venv-depth/Scripts/python.exe -m pip install 'numpy<3' opencv-python flask
if ($LASTEXITCODE) { throw 'Runtime installation failed' }
New-Item -ItemType Directory -Force models/depth_anything_v2 | Out-Null
$depthWeights = Join-Path $depthRoot 'models/depth_anything_v2/depth_anything_v2_vits.pth'
if (-not (Test-Path $depthWeights)) {
    Invoke-WebRequest 'https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/main/depth_anything_v2_vits.pth' -OutFile "$depthWeights.download"
    Move-Item -LiteralPath "$depthWeights.download" -Destination $depthWeights
}
$depthHash = Get-FileHash -LiteralPath $depthWeights -Algorithm SHA256
if ($depthHash.Hash.ToLowerInvariant() -ne '715fade13be8f229f8a70cc02066f656f2423a59effd0579197bbf57860e1378') {
    throw 'Checkpoint checksum does not match the tested Small model'
}
$depthHash
Write-Output 'Start Flask with: .venv-depth/Scripts/python.exe operator_ui/app.py'
