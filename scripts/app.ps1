#Requires -Version 5.1
<#
  app.ps1 — 便捷启动（单进程）：
    1) 前端若未构建则 `npm run build`（产物 frontend\dist 由 FastAPI 托管）
    2) 启动 FastAPI(:8000) 一个进程，同时提供 API + 前端页面
    3) 模型加载完成后自动打开浏览器到 http://localhost:8000
  关闭本窗口即停止服务。强制重建前端：  scripts\app.ps1 -Rebuild
#>
param([switch]$Rebuild)
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py       = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Backend  = Join-Path $RepoRoot 'backend'
$Frontend = Join-Path $RepoRoot 'frontend'
$DistIndex = Join-Path $Frontend 'dist\index.html'
$Url      = 'http://localhost:8000'

if (-not (Test-Path $Py)) { throw "未找到 venv，请先运行 scripts\setup.ps1" }

# 前端依赖
if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Write-Host "安装前端依赖 ..." -ForegroundColor Yellow
    npm install --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
}

# 构建前端（缺失或显式 -Rebuild 时）
if ($Rebuild -or -not (Test-Path $DistIndex)) {
    Write-Host "==> 构建前端 (npm run build) ..." -ForegroundColor Green
    npm run build --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
}

# 后台等待服务就绪后自动开浏览器。
# 模型预热在 lifespan 启动阶段同步完成，期间 /api/health 不会响应——
# 故轮询到它返回即代表“模型已就绪”，此时再开浏览器。
$opener = Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 180; $i++) {
        try {
            Invoke-WebRequest -Uri "$u/api/health" -TimeoutSec 2 -UseBasicParsing | Out-Null
            Start-Process $u
            break
        } catch { Start-Sleep -Seconds 1 }
    }
} -ArgumentList $Url

Write-Host "==> 启动 SHARP 服务 ($Url)" -ForegroundColor Green
Write-Host "    首次/重启需加载模型(约 20-30s)，就绪后自动打开浏览器。关闭本窗口即停止。" -ForegroundColor DarkGray
try {
    & $Py -m uvicorn app.main:app --app-dir $Backend --port 8000
} finally {
    Stop-Job   $opener -ErrorAction SilentlyContinue
    Remove-Job $opener -ErrorAction SilentlyContinue
}
