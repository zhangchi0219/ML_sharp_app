#Requires -Version 5.1
<#
  setup.ps1 — 一次性环境搭建（Windows / RTX 5080）
    1) 用系统 Python 建 .venv
    2) 安装 PyTorch (CUDA 12.8, 适配 RTX 5080 Blackwell sm_120)
    3) 安装 ml-sharp 预测路径所需依赖（不含 gsplat —— 仅渲染视频才需要它）
    4) editable 安装 third_party/ml-sharp（--no-deps，避免拉入 gsplat）
    5) 安装后端依赖（FastAPI 等）
    6) 校验 torch CUDA 与 sharp 可导入
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvDir  = Join-Path $RepoRoot '.venv'
$Py       = Join-Path $VenvDir 'Scripts\python.exe'
$Sharp    = Join-Path $RepoRoot 'third_party\ml-sharp'

function Invoke-Pip {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PipArgs)
    Write-Host "==> pip $($PipArgs -join ' ')" -ForegroundColor Cyan
    & $Py -m pip @PipArgs
    if ($LASTEXITCODE -ne 0) { throw "pip failed (exit $LASTEXITCODE): pip $($PipArgs -join ' ')" }
}

if (-not (Test-Path $Py)) {
    Write-Host "==> Creating venv at $VenvDir" -ForegroundColor Green
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
} else {
    Write-Host "==> Reusing existing venv at $VenvDir" -ForegroundColor Green
}

Invoke-Pip install --upgrade pip wheel

# 1) PyTorch CUDA 12.8 (Blackwell sm_120) —— 必须用 cu128 轮子，否则 5080 报 "no kernel image"
Invoke-Pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128

# 2) ml-sharp 预测依赖（去掉 gsplat）
Invoke-Pip install click "imageio[ffmpeg]" matplotlib pillow-heif plyfile scipy timm

# 3) 后端依赖
Invoke-Pip install fastapi "uvicorn[standard]" python-multipart sqlmodel pytest

# 注：不对 third_party/ml-sharp 执行 `pip install`。它是纯 Python 的 src-layout 包，
# 后端在运行时把 `third_party/ml-sharp/src` 加入 sys.path 直接 import（见 backend/app/sharp_runner.py）。
# 这样只安装标准 PyPI 依赖、不触发任何外部构建钩子。

# 4) 校验 torch + CUDA
Write-Host "==> Verifying torch + CUDA ..." -ForegroundColor Green
& $Py -c "import torch; print('torch', torch.__version__, '| cuda_available', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO-CUDA')"
if ($LASTEXITCODE -ne 0) { throw "torch verification failed" }

# 5) 校验 sharp 预测路径可导入（经 sys.path，不依赖 gsplat）
Write-Host "==> Verifying sharp import (no gsplat) ..." -ForegroundColor Green
$env:PYTHONPATH = Join-Path $Sharp 'src'
& $Py -c "from sharp.models import create_predictor, PredictorParams; from sharp.utils import io; from sharp.utils.gaussians import save_ply; print('sharp predict-path import OK')"
if ($LASTEXITCODE -ne 0) { throw "sharp import failed" }

Write-Host "`n[OK] Setup complete. venv: $VenvDir" -ForegroundColor Green
