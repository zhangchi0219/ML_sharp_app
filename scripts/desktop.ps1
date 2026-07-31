#Requires -Version 5.1
<#
  desktop.ps1 — 桌面应用启动：检查前置条件后，用 pythonw 拉起原生窗口。
    1) 前端依赖 / 构建产物缺失时先补上（-Rebuild 强制重建）
    2) 用 pythonw.exe 启动 desktop.py —— 无控制台窗口，窗口关闭即退出
  想看服务日志请改用 scripts\app.ps1（浏览器 + 可见控制台）。
#>
param([switch]$Rebuild)
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Pyw      = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
$Frontend = Join-Path $RepoRoot 'frontend'
$Entry    = Join-Path $RepoRoot 'desktop.py'

if (-not (Test-Path $Pyw)) { throw "未找到 venv，请先运行 scripts\setup.ps1" }

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Write-Host "安装前端依赖 ..." -ForegroundColor Yellow
    npm install --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
}

if ($Rebuild -or -not (Test-Path (Join-Path $Frontend 'dist\index.html'))) {
    Write-Host "==> 构建前端 (npm run build) ..." -ForegroundColor Green
    npm run build --prefix $Frontend
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
}

# pythonw 不带控制台；这里不 -Wait，脚本随即退出，窗口独立存活。
Start-Process -FilePath $Pyw -ArgumentList "`"$Entry`"" -WorkingDirectory $RepoRoot
