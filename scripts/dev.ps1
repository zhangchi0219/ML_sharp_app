#Requires -Version 5.1
<#
  dev.ps1 — 本地开发：同时启动后端(:8000) 与前端(:5173)。
    后端在新 PowerShell 窗口运行；前端在当前窗口运行（Ctrl+C 结束）。
    打开 http://localhost:5173
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py       = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Backend  = Join-Path $RepoRoot 'backend'
$Frontend = Join-Path $RepoRoot 'frontend'

if (-not (Test-Path $Py)) { throw "未找到 venv，请先运行 scripts\setup.ps1" }
if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Write-Host "前端依赖未安装，正在 npm install ..." -ForegroundColor Yellow
    npm install --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
}

Write-Host "==> 启动后端 (uvicorn :8000) ..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    '-NoExit', '-NoProfile', '-Command',
    "& '$Py' -m uvicorn app.main:app --app-dir '$Backend' --port 8000"
)

Write-Host "==> 启动前端 (vite :5173) ... 打开 http://localhost:5173" -ForegroundColor Green
npm run dev --prefix $Frontend
